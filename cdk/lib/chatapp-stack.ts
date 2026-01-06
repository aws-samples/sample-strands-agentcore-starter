/**
 * ChatApp Stack - Multi-Ingress support for chat application.
 * 
 * This stack supports three deployment modes:
 * 1. ECS Express Gateway Mode ('ecs') - Always-on container service (~$46/mo)
 * 2. Lambda Function URL Mode ('furl') - Serverless pay-per-use (~$12/mo)
 * 3. Both Modes ('both') - Deploy both simultaneously for A/B testing or migration
 * 
 * Deployment mode is configured via --ingress flag in deploy-all.sh which sets
 * the CDK context parameter 'ingress'.
 * 
 * Common Resources (all modes):
 * - ECR repository for container images
 * - S3 bucket for CodeBuild source
 * - CodeBuild project(s) for building Docker images
 * 
 * ECS-Specific Resources (mode = 'ecs' or 'both'):
 * - CloudWatch log group for container logs
 * - ECS Express Gateway Service with auto-scaling
 * - Custom resource to update deployment configuration
 * 
 * Lambda-Specific Resources (mode = 'furl' or 'both'):
 * - CloudWatch log group for Lambda logs
 * - Lambda Function with Web Adapter
 * - Lambda Function URL
 * 
 * Dependencies (consolidated stacks):
 * - Foundation Stack: IAM roles (execution, task, infrastructure), Secrets Manager secret
 * - Bedrock Stack: (values accessed via Secrets Manager)
 * - Agent Stack: (values accessed via Secrets Manager)
 * 
 * Exports:
 * - ChatAppRepositoryUri (always)
 * - EcsServiceUrl, EcsServiceArn (when mode = 'ecs' or 'both')
 * - LambdaFunctionUrl, LambdaFunctionArn (when mode = 'furl' or 'both')
 */

import * as cdk from 'aws-cdk-lib';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as codebuild from 'aws-cdk-lib/aws-codebuild';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import { NagSuppressions } from 'cdk-nag';
import { Construct } from 'constructs';
import { config, exportNames } from './config';
import { applyCommonSuppressions, applyBucketDeploymentSuppressions, applyCodeBuildSuppressions, applyCustomResourceSuppressions } from './nag-suppressions';
import * as path from 'path';

export class ChatAppStack extends cdk.Stack {
  // ========================================================================
  // Common Resources (always created)
  // ========================================================================
  
  /** ECR repository for chat application container images */
  public chatappRepository!: ecr.Repository;
  
  /** S3 bucket for CodeBuild source files */
  public sourceBucket!: s3.Bucket;
  
  /** Source deployment to S3 */
  private sourceDeployment!: s3deploy.BucketDeployment;
  
  // ========================================================================
  // ECS Resources (mode = 'ecs' or 'both')
  // ========================================================================
  
  /** CodeBuild project for building ECS Docker images */
  public ecsBuildProject?: codebuild.Project;
  
  /** CloudWatch log group for ECS container logs */
  public ecsLogGroup?: logs.LogGroup;
  
  /** ECS Express Gateway Service */
  public expressGatewayService?: ecs.CfnExpressGatewayService;
  
  // ========================================================================
  // Lambda Resources (mode = 'furl' or 'both')
  // ========================================================================
  
  /** CodeBuild project for building Lambda container images */
  public lambdaBuildProject?: codebuild.Project;
  
  /** CloudWatch log group for Lambda logs */
  public lambdaLogGroup?: logs.LogGroup;
  
  /** Lambda Function with Web Adapter */
  public lambdaFunction?: lambda.DockerImageFunction;
  
  /** Lambda Function URL (internal, IAM-protected) */
  public functionUrl?: lambda.FunctionUrl;
  
  /** CloudFront distribution for Lambda Function URL */
  public distribution?: cloudfront.Distribution;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const mode = config.deploymentMode;

    // ========================================================================
    // Create Common Resources
    // ========================================================================
    this.createCommonResources();

    // ========================================================================
    // Create Mode-Specific Resources
    // ========================================================================
    if (mode === 'ecs' || mode === 'both') {
      this.createEcsResources();
    }

    if (mode === 'furl' || mode === 'both') {
      this.createLambdaResources();
    }

    // ========================================================================
    // Create Stack Outputs
    // ========================================================================
    this.createOutputs();

    // ========================================================================
    // Apply CDK-Nag Suppressions
    // ========================================================================
    applyCommonSuppressions(this);
    applyBucketDeploymentSuppressions(this);
    applyCodeBuildSuppressions(this);
    applyCustomResourceSuppressions(this);

    // CloudFront suppressions (only when Lambda mode is enabled)
    if (config.deploymentMode === 'furl' || config.deploymentMode === 'both') {
      NagSuppressions.addResourceSuppressionsByPath(
        this,
        `/${config.appName}-ChatApp/Distribution/Resource`,
        [
          {
            id: 'AwsSolutions-CFR1',
            reason: 'Geo restrictions not required for this starter kit. Can be enabled for production deployments with specific regional requirements.',
          },
          {
            id: 'AwsSolutions-CFR2',
            reason: 'WAF integration not required for this starter kit. Application-level auth is handled by Cognito. WAF can be added for production deployments.',
          },
          {
            id: 'AwsSolutions-CFR4',
            reason: 'TLS 1.2 enforcement requires a custom domain with ACM certificate. Default CloudFront domain (*.cloudfront.net) uses AWS-managed certificate with TLSv1 minimum. For production, add a custom domain with ACM certificate.',
          },
        ]
      );
    }
  }

  /**
   * Create resources common to all deployment modes
   */
  private createCommonResources(): void {
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
    // Deploy ChatApp source files to S3
    // ========================================================================
    
    this.sourceDeployment = new s3deploy.BucketDeployment(this, 'ChatAppSourceDeployment', {
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
          ],
        }),
      ],
      destinationBucket: this.sourceBucket,
      destinationKeyPrefix: 'chatapp-source',
      prune: true,
      retainOnDelete: false,
      memoryLimit: 512,
    });
  }

  /**
   * Create ECS-specific resources (when mode = 'ecs' or 'both')
   */
  private createEcsResources(): void {
    const mode = config.deploymentMode;
    
    // Determine image tag based on mode
    const imageTag = mode === 'both' ? 'ecs-latest' : 'latest';

    // ========================================================================
    // CodeBuild Role and Project for ECS
    // ========================================================================
    
    const ecsCodeBuildRole = new iam.Role(this, 'EcsCodeBuildRole', {
      roleName: `${config.appName}-ecs-codebuild-role-${this.region}`,
      assumedBy: new iam.ServicePrincipal('codebuild.amazonaws.com'),
      description: 'CodeBuild role for building ECS ChatApp Docker images',
    });

    this.chatappRepository.grantPullPush(ecsCodeBuildRole);
    this.sourceBucket.grantRead(ecsCodeBuildRole);

    ecsCodeBuildRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'CloudWatchLogsAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:CreateLogGroup',
          'logs:CreateLogStream',
          'logs:PutLogEvents',
        ],
        resources: [
          `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/codebuild/${config.appName}-chatapp-ecs-build*`,
        ],
      })
    );

    // CodeBuild Project - uses AMD64 for ECS Express Mode compatibility
    this.ecsBuildProject = new codebuild.Project(this, 'EcsCodeBuildProject', {
      projectName: `${config.appName}-chatapp-ecs-build`,
      description: 'Build AMD64 Docker images for ChatApp ECS deployment',
      role: ecsCodeBuildRole,
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
          IMAGE_TAG: {
            type: codebuild.BuildEnvironmentVariableType.PLAINTEXT,
            value: imageTag,
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
              'echo Building ECS Docker image...',
              'docker build --platform linux/amd64 -t $ECR_REPO_URI:$IMAGE_TAG .',
              'docker tag $ECR_REPO_URI:$IMAGE_TAG $ECR_REPO_URI:ecs-$CODEBUILD_BUILD_NUMBER',
            ],
          },
          post_build: {
            commands: [
              'echo Build completed on `date`',
              'echo Pushing Docker images...',
              'docker push $ECR_REPO_URI:$IMAGE_TAG',
              'docker push $ECR_REPO_URI:ecs-$CODEBUILD_BUILD_NUMBER',
              'echo Images pushed successfully',
            ],
          },
        },
      }),
      timeout: cdk.Duration.minutes(30),
    });

    // ========================================================================
    // Trigger ECS CodeBuild
    // ========================================================================
    
    // Use build timestamp to force CodeBuild trigger on every deploy
    const buildTimestamp = new Date().toISOString();
    
    const triggerEcsBuild = new cr.AwsCustomResource(this, 'TriggerEcsBuild', {
      onCreate: {
        service: 'CodeBuild',
        action: 'startBuild',
        parameters: {
          projectName: this.ecsBuildProject.projectName,
          sourceTypeOverride: 'S3',
          sourceLocationOverride: `${this.sourceBucket.bucketName}/chatapp-source/`,
        },
        physicalResourceId: cr.PhysicalResourceId.fromResponse('build.id'),
      },
      onUpdate: {
        service: 'CodeBuild',
        action: 'startBuild',
        parameters: {
          projectName: this.ecsBuildProject.projectName,
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
          resources: [this.ecsBuildProject.projectArn],
        }),
      ]),
    });
    
    // Tag the custom resource with build timestamp for visibility
    cdk.Tags.of(triggerEcsBuild).add('BuildTimestamp', buildTimestamp);

    // Ensure build trigger waits for source deployment
    triggerEcsBuild.node.addDependency(this.sourceDeployment);

    // ========================================================================
    // Build Waiter for ECS - wait for CodeBuild to complete
    // ========================================================================
    
    const ecsBuildWaiterFunction = new lambda.Function(this, 'EcsBuildWaiterFunction', {
      functionName: `${config.appName}-ecs-build-waiter`,
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

    ecsBuildWaiterFunction.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['codebuild:BatchGetBuilds'],
        resources: [this.ecsBuildProject.projectArn],
      })
    );

    // Log group for ECS build waiter provider
    const ecsBuildWaiterLogGroup = new logs.LogGroup(this, 'EcsBuildWaiterLogGroup', {
      logGroupName: `/aws/lambda/${config.appName}-ecs-build-waiter-provider`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      retention: logs.RetentionDays.ONE_DAY,
    });

    const ecsBuildWaiterProvider = new cr.Provider(this, 'EcsBuildWaiterProvider', {
      onEventHandler: ecsBuildWaiterFunction,
      logGroup: ecsBuildWaiterLogGroup,
    });

    const ecsBuildWaiter = new cdk.CustomResource(this, 'EcsBuildWaiter', {
      serviceToken: ecsBuildWaiterProvider.serviceToken,
      properties: {
        BuildId: triggerEcsBuild.getResponseField('build.id'),
        Timestamp: Date.now().toString(),
      },
    });

    ecsBuildWaiter.node.addDependency(triggerEcsBuild);

    // ========================================================================
    // Create CloudWatch log group for ECS container logs
    // ========================================================================
    
    this.ecsLogGroup = new logs.LogGroup(this, 'EcsLogGroup', {
      logGroupName: `/ecs/${config.appName}/${config.ecsServiceName}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      retention: logs.RetentionDays.ONE_WEEK,
    });

    // ========================================================================
    // Create ECS Express Gateway Service
    // ========================================================================
    
    // Import IAM roles from Foundation stack
    const executionRoleArn = cdk.Fn.importValue(exportNames.executionRoleArn);
    const taskRoleArn = cdk.Fn.importValue(exportNames.taskRoleArn);
    const infrastructureRoleArn = cdk.Fn.importValue(exportNames.infrastructureRoleArn);
    
    // Import secret ARN from Foundation stack
    const secretArn = cdk.Fn.importValue(exportNames.secretArn);

    // Create ECS Express Gateway Service
    this.expressGatewayService = new ecs.CfnExpressGatewayService(this, 'ExpressGatewayService', {
      serviceName: config.ecsServiceName,
      
      // IAM roles
      executionRoleArn: executionRoleArn.toString(),
      infrastructureRoleArn: infrastructureRoleArn.toString(),
      taskRoleArn: taskRoleArn.toString(),
      
      // Resource allocation
      cpu: config.cpu.toString(),
      memory: config.memory.toString(),
      
      // Health check configuration
      healthCheckPath: '/health',
      
      // Auto-scaling configuration
      scalingTarget: {
        minTaskCount: config.minTasks,
        maxTaskCount: config.maxTasks,
        autoScalingMetric: 'AVERAGE_CPU',
        autoScalingTargetValue: 70,
      },
      
      // Primary container configuration
      primaryContainer: {
        image: `${this.chatappRepository.repositoryUri}:${imageTag}`,
        containerPort: config.containerPort,
        
        // CloudWatch Logs configuration
        awsLogsConfiguration: {
          logGroup: this.ecsLogGroup.logGroupName,
          logStreamPrefix: 'chatapp',
        },
        
        // Inject secrets as environment variables
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
    this.expressGatewayService.node.addDependency(this.ecsLogGroup);
    this.expressGatewayService.node.addDependency(ecsBuildWaiter);

    // ========================================================================
    // Create deployment configuration update custom resource
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
  }

  /**
   * Create Lambda-specific resources (when mode = 'furl' or 'both')
   */
  private createLambdaResources(): void {
    const mode = config.deploymentMode;
    
    // Determine image tag based on mode
    const imageTag = mode === 'both' ? 'lambda-latest' : 'latest';

    // ========================================================================
    // CodeBuild Role and Project for Lambda
    // ========================================================================
    
    const lambdaCodeBuildRole = new iam.Role(this, 'LambdaCodeBuildRole', {
      roleName: `${config.appName}-lambda-codebuild-role-${this.region}`,
      assumedBy: new iam.ServicePrincipal('codebuild.amazonaws.com'),
      description: 'CodeBuild role for building Lambda ChatApp container images',
    });

    this.chatappRepository.grantPullPush(lambdaCodeBuildRole);
    this.sourceBucket.grantRead(lambdaCodeBuildRole);

    lambdaCodeBuildRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'CloudWatchLogsAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:CreateLogGroup',
          'logs:CreateLogStream',
          'logs:PutLogEvents',
        ],
        resources: [
          `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/codebuild/${config.appName}-chatapp-lambda-build*`,
        ],
      })
    );

    // CodeBuild Project - builds Lambda container using Dockerfile.lambda
    this.lambdaBuildProject = new codebuild.Project(this, 'LambdaCodeBuildProject', {
      projectName: `${config.appName}-chatapp-lambda-build`,
      description: 'Build Lambda container images for ChatApp with Web Adapter',
      role: lambdaCodeBuildRole,
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
          IMAGE_TAG: {
            type: codebuild.BuildEnvironmentVariableType.PLAINTEXT,
            value: imageTag,
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
              'echo Building Lambda container image with Web Adapter...',
              'docker build -f Dockerfile.lambda --platform linux/amd64 -t $ECR_REPO_URI:$IMAGE_TAG .',
              'docker tag $ECR_REPO_URI:$IMAGE_TAG $ECR_REPO_URI:lambda-$CODEBUILD_BUILD_NUMBER',
            ],
          },
          post_build: {
            commands: [
              'echo Build completed on `date`',
              'echo Pushing Docker images...',
              'docker push $ECR_REPO_URI:$IMAGE_TAG',
              'docker push $ECR_REPO_URI:lambda-$CODEBUILD_BUILD_NUMBER',
              'echo Images pushed successfully',
            ],
          },
        },
      }),
      timeout: cdk.Duration.minutes(30),
    });

    // ========================================================================
    // Trigger Lambda CodeBuild
    // ========================================================================
    
    // Use build timestamp to force CodeBuild trigger on every deploy
    const lambdaBuildTimestamp = new Date().toISOString();
    
    const triggerLambdaBuild = new cr.AwsCustomResource(this, 'TriggerLambdaBuild', {
      onCreate: {
        service: 'CodeBuild',
        action: 'startBuild',
        parameters: {
          projectName: this.lambdaBuildProject.projectName,
          sourceTypeOverride: 'S3',
          sourceLocationOverride: `${this.sourceBucket.bucketName}/chatapp-source/`,
        },
        physicalResourceId: cr.PhysicalResourceId.fromResponse('build.id'),
      },
      onUpdate: {
        service: 'CodeBuild',
        action: 'startBuild',
        parameters: {
          projectName: this.lambdaBuildProject.projectName,
          sourceTypeOverride: 'S3',
          sourceLocationOverride: `${this.sourceBucket.bucketName}/chatapp-source/`,
          // Timestamp forces CloudFormation to see a change and trigger the build
          idempotencyToken: lambdaBuildTimestamp.replace(/[^a-zA-Z0-9]/g, '').substring(0, 64),
        },
        physicalResourceId: cr.PhysicalResourceId.fromResponse('build.id'),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['codebuild:StartBuild'],
          resources: [this.lambdaBuildProject.projectArn],
        }),
      ]),
    });

    // Tag the custom resource with build timestamp for visibility
    cdk.Tags.of(triggerLambdaBuild).add('BuildTimestamp', lambdaBuildTimestamp);

    // Ensure build trigger waits for source deployment
    triggerLambdaBuild.node.addDependency(this.sourceDeployment);

    // ========================================================================
    // Build Waiter for Lambda - wait for CodeBuild to complete
    // ========================================================================
    
    const lambdaBuildWaiterFunction = new lambda.Function(this, 'LambdaBuildWaiterFunction', {
      functionName: `${config.appName}-lambda-build-waiter`,
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

    lambdaBuildWaiterFunction.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['codebuild:BatchGetBuilds'],
        resources: [this.lambdaBuildProject.projectArn],
      })
    );

    // Log group for Lambda build waiter provider
    const lambdaBuildWaiterLogGroup = new logs.LogGroup(this, 'LambdaBuildWaiterLogGroup', {
      logGroupName: `/aws/lambda/${config.appName}-lambda-build-waiter-provider`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      retention: logs.RetentionDays.ONE_DAY,
    });

    const lambdaBuildWaiterProvider = new cr.Provider(this, 'LambdaBuildWaiterProvider', {
      onEventHandler: lambdaBuildWaiterFunction,
      logGroup: lambdaBuildWaiterLogGroup,
    });

    const lambdaBuildWaiter = new cdk.CustomResource(this, 'LambdaBuildWaiter', {
      serviceToken: lambdaBuildWaiterProvider.serviceToken,
      properties: {
        BuildId: triggerLambdaBuild.getResponseField('build.id'),
        Timestamp: Date.now().toString(),
      },
    });

    lambdaBuildWaiter.node.addDependency(triggerLambdaBuild);

    // ========================================================================
    // CloudWatch Log Group for Lambda
    // ========================================================================
    
    this.lambdaLogGroup = new logs.LogGroup(this, 'LambdaLogGroup', {
      logGroupName: `/aws/lambda/${config.lambdaFunctionName}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      retention: logs.RetentionDays.THREE_DAYS,
    });

    // ========================================================================
    // Lambda Function with Web Adapter
    // ========================================================================
    
    // Import IAM role and secret from Foundation stack
    const taskRoleArn = cdk.Fn.importValue(exportNames.taskRoleArn);
    const secretArn = cdk.Fn.importValue(exportNames.secretArn);
    
    const taskRole = iam.Role.fromRoleArn(this, 'TaskRole', taskRoleArn);
    const secret = secretsmanager.Secret.fromSecretCompleteArn(this, 'Secret', secretArn);
    
    // Create Lambda function from container image
    this.lambdaFunction = new lambda.DockerImageFunction(this, 'LambdaFunction', {
      functionName: config.lambdaFunctionName,
      description: 'FastAPI chat application with Lambda Web Adapter for SSE streaming',
      code: lambda.DockerImageCode.fromEcr(this.chatappRepository, {
        tagOrDigest: imageTag,
      }),
      memorySize: config.lambdaMemory,
      timeout: cdk.Duration.seconds(config.lambdaTimeout),
      role: taskRole,
      logGroup: this.lambdaLogGroup,
      
      // Environment variables for Lambda Web Adapter (non-secret)
      environment: {
        'PORT': '8080',
        'LOG_LEVEL': 'INFO',
        'AWS_LWA_INVOKE_MODE': 'response_stream',  // Enable SSE streaming
        'AWS_LWA_PORT': '8080',
      },
    });
    
    // Grant secret read permissions
    secret.grantRead(this.lambdaFunction);
    
    // Grant CloudWatch Logs write permissions
    // Required because the Lambda uses an imported role from Foundation stack
    this.lambdaLogGroup.grantWrite(this.lambdaFunction);
    // Lambda function depends on build completion
    this.lambdaFunction.node.addDependency(lambdaBuildWaiter);
    
    // Add environment variables from Secrets Manager
    const secretFields: { [key: string]: string } = {
      'COGNITO_USER_POOL_ID': 'cognito_user_pool_id',
      'COGNITO_CLIENT_ID': 'cognito_client_id',
      'COGNITO_CLIENT_SECRET': 'cognito_client_secret',
      'AGENTCORE_RUNTIME_ARN': 'agentcore_runtime_arn',
      'MEMORY_ID': 'memory_id',
      'USAGE_TABLE_NAME': 'usage_table_name',
      'FEEDBACK_TABLE_NAME': 'feedback_table_name',
      'GUARDRAIL_TABLE_NAME': 'guardrail_table_name',
      'PROMPT_TEMPLATES_TABLE_NAME': 'prompt_templates_table_name',
      'GUARDRAIL_ID': 'guardrail_id',
      'GUARDRAIL_VERSION': 'guardrail_version',
      'KB_ID': 'kb_id',
    };
    
    // Add each secret as an environment variable
    for (const [envVar, secretField] of Object.entries(secretFields)) {
      this.lambdaFunction.addEnvironment(
        envVar,
        secret.secretValueFromJson(secretField).unsafeUnwrap()
      );
    }

    // ========================================================================
    // Force Lambda to use latest container image after build
    // ========================================================================
    
    // Custom resource to update Lambda function code after CodeBuild completes
    // This ensures the Lambda uses the newly built container image
    const updateLambdaCode = new cr.AwsCustomResource(this, 'UpdateLambdaCode', {
      onCreate: {
        service: 'Lambda',
        action: 'updateFunctionCode',
        parameters: {
          FunctionName: this.lambdaFunction.functionName,
          ImageUri: `${this.chatappRepository.repositoryUri}:${imageTag}`,
        },
        physicalResourceId: cr.PhysicalResourceId.of(`${this.lambdaFunction.functionName}-code-update`),
      },
      onUpdate: {
        service: 'Lambda',
        action: 'updateFunctionCode',
        parameters: {
          FunctionName: this.lambdaFunction.functionName,
          ImageUri: `${this.chatappRepository.repositoryUri}:${imageTag}`,
        },
        physicalResourceId: cr.PhysicalResourceId.of(`${this.lambdaFunction.functionName}-code-update-${lambdaBuildTimestamp.replace(/[^a-zA-Z0-9]/g, '')}`),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['lambda:UpdateFunctionCode'],
          resources: [this.lambdaFunction.functionArn],
        }),
      ]),
    });

    // Ensure Lambda code update happens after build completes
    updateLambdaCode.node.addDependency(lambdaBuildWaiter);

    // ========================================================================
    // Lambda Function URL with IAM Auth + CloudFront OAC
    // ========================================================================
    
    // Create Function URL with IAM authentication (not publicly accessible)
    this.functionUrl = this.lambdaFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.AWS_IAM,  // IAM auth - CloudFront will sign requests
      invokeMode: lambda.InvokeMode.RESPONSE_STREAM,  // Enable SSE streaming
    });

    // Import access logs bucket for CloudFront logging
    const accessLogsBucketName = cdk.Fn.importValue(`${config.appName}-AccessLogsBucketName`);
    const accessLogsBucket = s3.Bucket.fromBucketName(this, 'CloudFrontAccessLogsBucket', accessLogsBucketName);

    // ========================================================================
    // Lambda@Edge for SHA256 payload signing (required for POST/PUT with OAC)
    // ========================================================================
    
    // Lambda@Edge function to compute SHA256 hash of request body
    // Required because CloudFront OAC with Lambda Function URLs needs
    // x-amz-content-sha256 header for POST/PUT requests
    const edgeFunction = new cloudfront.experimental.EdgeFunction(this, 'PayloadHashFunction', {
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: 'index.handler',
      code: lambda.Code.fromInline(`
const crypto = require('crypto');

exports.handler = async (event) => {
  const request = event.Records[0].cf.request;
  
  // Only process requests with a body (POST, PUT, PATCH)
  if (request.body && request.body.data) {
    // Decode the body (base64 if binary, otherwise plain text)
    const body = request.body.encoding === 'base64' 
      ? Buffer.from(request.body.data, 'base64')
      : request.body.data;
    
    // Compute SHA256 hash
    const hash = crypto.createHash('sha256').update(body).digest('hex');
    
    // Add the x-amz-content-sha256 header
    request.headers['x-amz-content-sha256'] = [{
      key: 'x-amz-content-sha256',
      value: hash
    }];
  } else if (['POST', 'PUT', 'PATCH'].includes(request.method)) {
    // Empty body - use hash of empty string
    const emptyHash = crypto.createHash('sha256').update('').digest('hex');
    request.headers['x-amz-content-sha256'] = [{
      key: 'x-amz-content-sha256',
      value: emptyHash
    }];
  }
  
  return request;
};
      `),
      description: 'Computes SHA256 hash for request body to support CloudFront OAC with Lambda Function URL',
    });

    // Suppress CDK-Nag findings for Lambda@Edge function (deployed in separate us-east-1 stack)
    // The EdgeFunction creates a cross-region stack, so we need to suppress on the stack level
    const edgeStack = cdk.Stack.of(edgeFunction.node.defaultChild as cdk.CfnResource);
    NagSuppressions.addStackSuppressions(edgeStack, [
      {
        id: 'AwsSolutions-IAM4',
        reason: 'Lambda@Edge requires AWSLambdaBasicExecutionRole for CloudWatch Logs. This is the standard pattern for Lambda functions.',
        appliesTo: ['Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'],
      },
      {
        id: 'AwsSolutions-L1',
        reason: 'Using Node.js 22.x which is the latest supported runtime for Lambda@Edge.',
      },
    ]);

    // Create CloudFront distribution with Lambda Function URL origin and OAC
    this.distribution = new cloudfront.Distribution(this, 'Distribution', {
      comment: `${config.appName} - CloudFront distribution for Lambda Function URL`,
      defaultBehavior: {
        // Use FunctionUrlOrigin.withOriginAccessControl for proper SigV4 signing
        origin: origins.FunctionUrlOrigin.withOriginAccessControl(this.functionUrl),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
        cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
        originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        // Add Lambda@Edge to compute payload hash for POST/PUT requests
        edgeLambdas: [
          {
            functionVersion: edgeFunction.currentVersion,
            eventType: cloudfront.LambdaEdgeEventType.ORIGIN_REQUEST,
            includeBody: true,  // Required to access request body
          },
        ],
      },
      // CFR3: Enable access logging
      logBucket: accessLogsBucket,
      logFilePrefix: 'cloudfront/',
      // CFR4: Enforce TLSv1.2 minimum
      minimumProtocolVersion: cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
    });

    // Grant CloudFront permission to invoke the Lambda Function URL
    this.lambdaFunction.addPermission('CloudFrontInvoke', {
      principal: new iam.ServicePrincipal('cloudfront.amazonaws.com'),
      action: 'lambda:InvokeFunctionUrl',
      sourceArn: `arn:aws:cloudfront::${this.account}:distribution/${this.distribution.distributionId}`,
    });
  }

  /**
   * Create stack outputs based on deployment mode
   */
  private createOutputs(): void {
    const mode = config.deploymentMode;

    // ========================================================================
    // Common Outputs
    // ========================================================================
    
    new cdk.CfnOutput(this, 'ChatAppRepositoryUri', {
      value: this.chatappRepository.repositoryUri,
      description: 'ECR repository URI for chat application container images',
      exportName: exportNames.chatappRepositoryUri,
    });

    new cdk.CfnOutput(this, 'DeploymentMode', {
      value: mode,
      description: 'Deployment mode: ecs, furl, or both',
    });

    // ========================================================================
    // ECS Outputs (when mode = 'ecs' or 'both')
    // ========================================================================
    
    if (mode === 'ecs' || mode === 'both') {
      new cdk.CfnOutput(this, 'EcsServiceName', {
        value: config.ecsServiceName,
        description: 'ECS Express Mode service name (use deploy-all.sh to get actual URL)',
        exportName: exportNames.ecsServiceUrl,
      });

      new cdk.CfnOutput(this, 'EcsServiceArn', {
        value: this.expressGatewayService!.attrServiceArn,
        description: 'ECS Express Gateway Service ARN',
        exportName: exportNames.ecsServiceArn,
      });

      new cdk.CfnOutput(this, 'EcsLogGroupName', {
        value: this.ecsLogGroup!.logGroupName,
        description: 'CloudWatch log group name for ECS container logs',
      });
    }

    // ========================================================================
    // Lambda Outputs (when mode = 'furl' or 'both')
    // ========================================================================
    
    if (mode === 'furl' || mode === 'both') {
      new cdk.CfnOutput(this, 'LambdaFunctionUrl', {
        value: `https://${this.distribution!.distributionDomainName}`,
        description: 'CloudFront URL for Lambda Function (use this for access)',
        exportName: exportNames.lambdaFunctionUrl,
      });

      new cdk.CfnOutput(this, 'CloudFrontDistributionId', {
        value: this.distribution!.distributionId,
        description: 'CloudFront distribution ID',
      });

      new cdk.CfnOutput(this, 'LambdaFunctionArn', {
        value: this.lambdaFunction!.functionArn,
        description: 'Lambda function ARN',
        exportName: exportNames.lambdaFunctionArn,
      });

      new cdk.CfnOutput(this, 'LambdaFunctionName', {
        value: this.lambdaFunction!.functionName,
        description: 'Lambda function name for logs and monitoring',
      });

      new cdk.CfnOutput(this, 'LambdaLogGroupName', {
        value: this.lambdaLogGroup!.logGroupName,
        description: 'CloudWatch log group name for Lambda logs',
      });
    }
  }
}
