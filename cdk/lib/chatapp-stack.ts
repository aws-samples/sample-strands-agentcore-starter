/**
 * ChatApp Stack - ECS Express Mode service for the chat application.
 * 
 * This stack creates:
 * - ECR repository for container images
 * - S3 bucket for CodeBuild source
 * - CodeBuild project for building Docker images
 * - CloudWatch log group for container logs
 * - ECS Express Gateway Service with auto-scaling
 * - Custom resource to update deployment configuration
 * 
 * Dependencies (consolidated stacks):
 * - Foundation Stack: IAM roles (execution, task, infrastructure), Secrets Manager secret
 * - Bedrock Stack: (values accessed via Secrets Manager)
 * - Agent Stack: (values accessed via Secrets Manager)
 * 
 * Exports:
 * - ServiceUrl
 * - ServiceArn
 * - ChatAppRepositoryUri
 */

import * as cdk from 'aws-cdk-lib';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as codebuild from 'aws-cdk-lib/aws-codebuild';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as cr from 'aws-cdk-lib/custom-resources';
import { NagSuppressions } from 'cdk-nag';
import { Construct } from 'constructs';
import { config, exportNames } from './config';
import { applyCommonSuppressions, applyBucketDeploymentSuppressions, applyCodeBuildSuppressions } from './nag-suppressions';
import * as path from 'path';

export class ChatAppStack extends cdk.Stack {
  /** ECR repository for chat application container images */
  public readonly chatappRepository: ecr.Repository;
  
  /** S3 bucket for CodeBuild source files */
  public readonly sourceBucket: s3.Bucket;
  
  /** CodeBuild project for building ChatApp Docker images */
  public readonly buildProject: codebuild.Project;
  
  /** CloudWatch log group for container logs */
  public readonly logGroup: logs.LogGroup;
  
  /** ECS Express Gateway Service */
  public readonly expressGatewayService: ecs.CfnExpressGatewayService;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ========================================================================
    // ECR Repository for ChatApp container images
    // ========================================================================
    
    this.chatappRepository = new ecr.Repository(this, 'ChatAppRepository', {
      repositoryName: config.chatappRepoName,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      emptyOnDelete: true,
      imageScanOnPush: true,
      lifecycleRules: [
        {
          description: 'Keep only 5 most recent images',
          maxImageCount: 5,
          rulePriority: 1,
          tagStatus: ecr.TagStatus.ANY,
        },
      ],
    });

    // ========================================================================
    // S3 Bucket for CodeBuild source
    // ========================================================================
    
    // Import access logs bucket from Foundation stack
    const accessLogsBucketName = cdk.Fn.importValue(`${config.appName}-AccessLogsBucketName`);
    const accessLogsBucket = s3.Bucket.fromBucketName(this, 'ImportedAccessLogsBucket', accessLogsBucketName);

    this.sourceBucket = new s3.Bucket(this, 'ChatAppSourceBucket', {
      bucketName: `${config.appName}-chatapp-source-${this.account}-${this.region}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      serverAccessLogsBucket: accessLogsBucket,
      serverAccessLogsPrefix: 'chatapp-source/',
      lifecycleRules: [
        {
          id: 'ExpireOldObjects',
          enabled: true,
          expiration: cdk.Duration.days(7),
        },
      ],
    });

    // Acknowledge that logging permissions are handled in Foundation stack
    cdk.Annotations.of(this.sourceBucket).acknowledgeWarning('@aws-cdk/aws-s3:accessLogsPolicyNotAdded', 'Logging permissions added to access logs bucket in Foundation stack');

    // ========================================================================
    // CodeBuild Role and Project
    // ========================================================================
    
    const codeBuildRole = new iam.Role(this, 'ChatAppCodeBuildRole', {
      roleName: `${config.appName}-chatapp-codebuild-role-${this.region}`,
      assumedBy: new iam.ServicePrincipal('codebuild.amazonaws.com'),
      description: 'CodeBuild role for building ChatApp Docker images',
    });

    this.chatappRepository.grantPullPush(codeBuildRole);
    this.sourceBucket.grantRead(codeBuildRole);

    codeBuildRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'CloudWatchLogsAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:CreateLogGroup',
          'logs:CreateLogStream',
          'logs:PutLogEvents',
        ],
        resources: [
          `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/codebuild/${config.appName}-chatapp-build*`,
        ],
      })
    );

    // CodeBuild Project - uses AMD64 for ECS Express Mode compatibility
    this.buildProject = new codebuild.Project(this, 'ChatAppBuildProject', {
      projectName: `${config.appName}-chatapp-build`,
      description: 'Build AMD64 Docker images for ChatApp',
      role: codeBuildRole,
      source: codebuild.Source.s3({
        bucket: this.sourceBucket,
        path: 'chatapp-source/',
      }),
      environment: {
        buildImage: codebuild.LinuxBuildImage.AMAZON_LINUX_2_5,
        computeType: codebuild.ComputeType.SMALL,
        privileged: true,
        environmentVariables: {
          AWS_ACCOUNT_ID: {
            type: codebuild.BuildEnvironmentVariableType.PLAINTEXT,
            value: this.account,
          },
          AWS_REGION: {
            type: codebuild.BuildEnvironmentVariableType.PLAINTEXT,
            value: this.region,
          },
          ECR_REPO_URI: {
            type: codebuild.BuildEnvironmentVariableType.PLAINTEXT,
            value: this.chatappRepository.repositoryUri,
          },
        },
      },
      buildSpec: codebuild.BuildSpec.fromObject({
        version: '0.2',
        phases: {
          pre_build: {
            commands: [
              'echo Logging in to Amazon ECR...',
              'aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com',
            ],
          },
          build: {
            commands: [
              'echo Build started on `date`',
              'echo Building the Docker image...',
              'docker build --platform linux/amd64 -t $ECR_REPO_URI:latest .',
              'docker tag $ECR_REPO_URI:latest $ECR_REPO_URI:$CODEBUILD_BUILD_NUMBER',
            ],
          },
          post_build: {
            commands: [
              'echo Build completed on `date`',
              'echo Pushing the Docker image...',
              'docker push $ECR_REPO_URI:latest',
              'docker push $ECR_REPO_URI:$CODEBUILD_BUILD_NUMBER',
              'echo Image pushed successfully',
            ],
          },
        },
      }),
      timeout: cdk.Duration.minutes(30),
    });

    // ========================================================================
    // Deploy ChatApp source files to S3
    // ========================================================================
    
    const chatappSourceDeployment = new s3deploy.BucketDeployment(this, 'ChatAppSourceDeployment', {
      sources: [
        s3deploy.Source.asset(path.join(__dirname, '../../chatapp'), {
          exclude: [
            '.venv/**',
            'venv/**',
            '__pycache__/**',
            '*.pyc',
            '.git/**',
            'node_modules/**',
            '.env',
            '*.egg-info/**',
            '.pytest_cache/**',
            '.mypy_cache/**',
            '.ruff_cache/**',
            'deploy/**',
            '*.log',
            '.DS_Store',
            'tests/**',
          ],
        }),
      ],
      destinationBucket: this.sourceBucket,
      destinationKeyPrefix: 'chatapp-source',
      prune: true,
      retainOnDelete: false,
      memoryLimit: 512,
    });

    // ========================================================================
    // Trigger CodeBuild
    // ========================================================================
    
    // Use build timestamp to force CodeBuild trigger on every deploy
    const buildTimestamp = new Date().toISOString();
    
    const triggerBuild = new cr.AwsCustomResource(this, 'TriggerChatAppBuild', {
      onCreate: {
        service: 'CodeBuild',
        action: 'startBuild',
        parameters: {
          projectName: this.buildProject.projectName,
          sourceTypeOverride: 'S3',
          sourceLocationOverride: `${this.sourceBucket.bucketName}/chatapp-source/`,
        },
        physicalResourceId: cr.PhysicalResourceId.fromResponse('build.id'),
      },
      onUpdate: {
        service: 'CodeBuild',
        action: 'startBuild',
        parameters: {
          projectName: this.buildProject.projectName,
          sourceTypeOverride: 'S3',
          sourceLocationOverride: `${this.sourceBucket.bucketName}/chatapp-source/`,
          // Timestamp forces CloudFormation to see a change and trigger the build
          idempotencyToken: buildTimestamp.replace(/[^a-zA-Z0-9]/g, '').substring(0, 64),
        },
        physicalResourceId: cr.PhysicalResourceId.fromResponse('build.id'),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['codebuild:StartBuild'],
          resources: [this.buildProject.projectArn],
        }),
      ]),
    });
    
    // Tag the custom resource with build timestamp for visibility
    cdk.Tags.of(triggerBuild).add('BuildTimestamp', buildTimestamp);

    triggerBuild.node.addDependency(chatappSourceDeployment);

    // ========================================================================
    // Build Waiter - wait for CodeBuild to complete
    // ========================================================================
    
    const buildWaiterFunction = new lambda.Function(this, 'ChatAppBuildWaiterFunction', {
      functionName: `${config.appName}-chatapp-build-waiter`,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'index.handler',
      timeout: cdk.Duration.minutes(14),
      memorySize: 128,
      code: lambda.Code.fromInline(`
import boto3
import time
import json
import cfnresponse

def handler(event, context):
    print(f"Event: {json.dumps(event)}")
    
    if event['RequestType'] == 'Delete':
        cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
        return
    
    try:
        build_id = event['ResourceProperties']['BuildId']
        codebuild = boto3.client('codebuild')
        
        max_attempts = 28
        for attempt in range(max_attempts):
            response = codebuild.batch_get_builds(ids=[build_id])
            
            if not response['builds']:
                raise Exception(f"Build {build_id} not found")
            
            build = response['builds'][0]
            status = build['buildStatus']
            
            print(f"Attempt {attempt + 1}: Build status = {status}")
            
            if status == 'SUCCEEDED':
                cfnresponse.send(event, context, cfnresponse.SUCCESS, {
                    'BuildId': build_id,
                    'Status': status
                })
                return
            elif status in ['FAILED', 'FAULT', 'STOPPED', 'TIMED_OUT']:
                error_msg = f"Build {build_id} failed with status: {status}"
                print(error_msg)
                cfnresponse.send(event, context, cfnresponse.FAILED, {}, reason=error_msg)
                return
            
            time.sleep(30)
        
        error_msg = f"Build {build_id} timed out after 14 minutes"
        print(error_msg)
        cfnresponse.send(event, context, cfnresponse.FAILED, {}, reason=error_msg)
        
    except Exception as e:
        print(f"Error: {str(e)}")
        cfnresponse.send(event, context, cfnresponse.FAILED, {}, reason=str(e))
`),
    });

    buildWaiterFunction.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['codebuild:BatchGetBuilds'],
        resources: [this.buildProject.projectArn],
      })
    );

    const buildWaiterProviderLogGroup = new logs.LogGroup(this, 'ChatAppBuildWaiterProviderLogs', {
      retention: logs.RetentionDays.ONE_DAY,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const buildWaiterProvider = new cr.Provider(this, 'ChatAppBuildWaiterProvider', {
      onEventHandler: buildWaiterFunction,
      logGroup: buildWaiterProviderLogGroup,
    });

    const buildWaiter = new cdk.CustomResource(this, 'ChatAppBuildWaiter', {
      serviceToken: buildWaiterProvider.serviceToken,
      properties: {
        BuildId: triggerBuild.getResponseField('build.id'),
        Timestamp: Date.now().toString(),
      },
    });

    buildWaiter.node.addDependency(triggerBuild);


    // ========================================================================
    // Task 13.2: Create CloudWatch log group for container logs
    // Requirements: 8.6
    // ========================================================================
    
    this.logGroup = new logs.LogGroup(this, 'ChatAppLogGroup', {
      logGroupName: `/ecs/${config.appName}/${config.ecsServiceName}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      retention: logs.RetentionDays.ONE_WEEK,
    });

    // ========================================================================
    // Task 13.3: Create ECS Express Gateway Service
    // Requirements: 8.2, 8.3, 8.4, 8.5
    // ========================================================================
    
    // Import IAM roles from Foundation stack
    const executionRoleArn = cdk.Fn.importValue(exportNames.executionRoleArn);
    const taskRoleArn = cdk.Fn.importValue(exportNames.taskRoleArn);
    const infrastructureRoleArn = cdk.Fn.importValue(exportNames.infrastructureRoleArn);
    
    // Import secret ARN from Foundation stack
    // Note: The secret contains values from Foundation, Bedrock, and Agent stacks
    const secretArn = cdk.Fn.importValue(exportNames.secretArn);

    // Create ECS Express Gateway Service
    this.expressGatewayService = new ecs.CfnExpressGatewayService(this, 'ExpressGatewayService', {
      serviceName: config.ecsServiceName,
      
      // IAM roles (Requirements: 8.2)
      executionRoleArn: executionRoleArn.toString(),
      infrastructureRoleArn: infrastructureRoleArn.toString(),
      taskRoleArn: taskRoleArn.toString(),
      
      // Resource allocation (Requirements: 8.2)
      cpu: config.cpu.toString(),
      memory: config.memory.toString(),
      
      // Health check configuration (Requirements: 8.4)
      healthCheckPath: '/health',
      
      // Auto-scaling configuration (Requirements: 8.3)
      scalingTarget: {
        minTaskCount: config.minTasks,
        maxTaskCount: config.maxTasks,
        autoScalingMetric: 'AVERAGE_CPU',
        autoScalingTargetValue: 70,
      },
      
      // Primary container configuration (Requirements: 8.5)
      primaryContainer: {
        image: `${this.chatappRepository.repositoryUri}:latest`,
        containerPort: config.containerPort,
        
        // CloudWatch Logs configuration
        awsLogsConfiguration: {
          logGroup: this.logGroup.logGroupName,
          logStreamPrefix: 'chatapp',
        },
        
        // Inject secrets as environment variables (Requirements: 8.5)
        secrets: [
          {
            name: 'COGNITO_USER_POOL_ID',
            valueFrom: `${secretArn}:cognito_user_pool_id::`,
          },
          {
            name: 'COGNITO_CLIENT_ID',
            valueFrom: `${secretArn}:cognito_client_id::`,
          },
          {
            name: 'COGNITO_CLIENT_SECRET',
            valueFrom: `${secretArn}:cognito_client_secret::`,
          },
          {
            name: 'AGENTCORE_RUNTIME_ARN',
            valueFrom: `${secretArn}:agentcore_runtime_arn::`,
          },
          {
            name: 'MEMORY_ID',
            valueFrom: `${secretArn}:memory_id::`,
          },
          {
            name: 'USAGE_TABLE_NAME',
            valueFrom: `${secretArn}:usage_table_name::`,
          },
          {
            name: 'FEEDBACK_TABLE_NAME',
            valueFrom: `${secretArn}:feedback_table_name::`,
          },
          {
            name: 'GUARDRAIL_TABLE_NAME',
            valueFrom: `${secretArn}:guardrail_table_name::`,
          },
          {
            name: 'PROMPT_TEMPLATES_TABLE_NAME',
            valueFrom: `${secretArn}:prompt_templates_table_name::`,
          },
          {
            name: 'GUARDRAIL_ID',
            valueFrom: `${secretArn}:guardrail_id::`,
          },
          {
            name: 'GUARDRAIL_VERSION',
            valueFrom: `${secretArn}:guardrail_version::`,
          },
          {
            name: 'KB_ID',
            valueFrom: `${secretArn}:kb_id::`,
          },
        ],
        
        // Environment variables (non-secret)
        environment: [
          {
            name: 'AWS_REGION',
            value: this.region,
          },
          {
            name: 'PORT',
            value: config.containerPort.toString(),
          },
          {
            name: 'LOG_LEVEL',
            value: 'INFO',
          },
        ],
      },
    });

    // Ensure the service depends on the log group and build completion
    this.expressGatewayService.node.addDependency(this.logGroup);
    this.expressGatewayService.node.addDependency(buildWaiter);


    // ========================================================================
    // Task 13.4: Create deployment configuration update custom resource
    // Requirements: 8.7
    // ========================================================================
    
    // Custom resource to update ECS service deployment configuration
    // This sets bakeTimeInMinutes=0 and canaryPercent=100 for faster deployments
    const updateDeploymentConfig = new cr.AwsCustomResource(this, 'UpdateDeploymentConfig', {
      onCreate: {
        service: 'ECS',
        action: 'updateService',
        parameters: {
          cluster: 'default',
          service: config.ecsServiceName,
          deploymentConfiguration: {
            bakeTimeInMinutes: 0,
            canaryConfiguration: {
              canaryPercent: 100.0,
              canaryBakeTimeInMinutes: 0,
            },
          },
        },
        physicalResourceId: cr.PhysicalResourceId.of(`${config.ecsServiceName}-deployment-config`),
      },
      onUpdate: {
        service: 'ECS',
        action: 'updateService',
        parameters: {
          cluster: 'default',
          service: config.ecsServiceName,
          deploymentConfiguration: {
            bakeTimeInMinutes: 0,
            canaryConfiguration: {
              canaryPercent: 100.0,
              canaryBakeTimeInMinutes: 0,
            },
          },
        },
        physicalResourceId: cr.PhysicalResourceId.of(`${config.ecsServiceName}-deployment-config`),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['ecs:UpdateService'],
          resources: [
            `arn:aws:ecs:${this.region}:${this.account}:service/default/${config.ecsServiceName}`,
          ],
        }),
      ]),
    });

    // Ensure this runs after the Express Gateway Service is created
    updateDeploymentConfig.node.addDependency(this.expressGatewayService);

    // ========================================================================
    // Task 13.5: Add stack outputs and exports
    // Requirements: 8.9
    // ========================================================================
    
    // Export ECR repository URI
    new cdk.CfnOutput(this, 'ChatAppRepositoryUri', {
      value: this.chatappRepository.repositoryUri,
      description: 'ECR repository URI for chat application container images',
      exportName: exportNames.chatappRepositoryUri,
    });

    // Note: The actual service URL is not available as a CloudFormation attribute.
    // The deploy-all.sh script fetches the real URL from the ECS API after deployment.
    // This output provides a placeholder that indicates where to find the URL.
    new cdk.CfnOutput(this, 'ServiceName', {
      value: config.ecsServiceName,
      description: 'ECS Express Mode service name (use deploy-all.sh to get actual URL)',
      exportName: exportNames.serviceUrl,
    });

    // Export Service ARN
    new cdk.CfnOutput(this, 'ServiceArn', {
      value: this.expressGatewayService.attrServiceArn,
      description: 'ECS Express Gateway Service ARN',
      exportName: exportNames.serviceArn,
    });

    // Output log group name for reference
    new cdk.CfnOutput(this, 'LogGroupName', {
      value: this.logGroup.logGroupName,
      description: 'CloudWatch log group name for container logs',
    });

    // ========================================================================
    // CDK-NAG SUPPRESSIONS
    // ========================================================================
    
    applyCommonSuppressions(this);
    applyBucketDeploymentSuppressions(this);
    applyCodeBuildSuppressions(this);

    // Suppress CodeBuild role wildcards
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-ChatApp/ChatAppCodeBuildRole/DefaultPolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'CodeBuild log groups include build number. Scoped to specific project prefix.',
          appliesTo: [
            `Resource::arn:aws:logs:${this.region}:${this.account}:log-group:/aws/codebuild/${config.appName}-chatapp-build*`,
            `Resource::arn:aws:logs:${this.region}:${this.account}:log-group:/aws/codebuild/<ChatAppBuildProjectCED7EC7C>:*`,
          ],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'CodeBuild report groups include dynamic names. Scoped to specific project.',
          appliesTo: [`Resource::arn:aws:codebuild:${this.region}:${this.account}:report-group/<ChatAppBuildProjectCED7EC7C>-*`],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'CodeBuild needs access to all objects in source bucket.',
          appliesTo: ['Resource::<ChatAppSourceBucket82B12907.Arn>/*'],
        },
      ]
    );

    // Suppress BucketDeployment wildcards
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-ChatApp/Custom::CDKBucketDeployment8693BB64968944B69AAFB0CC9EB8756C512MiB/ServiceRole/DefaultPolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'BucketDeployment needs access to CDK assets bucket for deployment.',
          appliesTo: [`Resource::arn:aws:s3:::cdk-hnb659fds-assets-${this.account}-${this.region}/*`],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'BucketDeployment needs access to all objects in destination bucket.',
          appliesTo: ['Resource::<ChatAppSourceBucket82B12907.Arn>/*'],
        },
      ]
    );

    // Suppress build waiter provider wildcards
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-ChatApp/ChatAppBuildWaiterProvider/framework-onEvent/ServiceRole/DefaultPolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'CDK Provider framework requires lambda:InvokeFunction with wildcard for versioned invocations.',
          appliesTo: ['Resource::<ChatAppBuildWaiterFunction8502DDEE.Arn>:*'],
        },
      ]
    );
  }
}
