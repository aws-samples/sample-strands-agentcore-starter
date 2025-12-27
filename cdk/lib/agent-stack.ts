/**
 * Agent Stack - Consolidated stack for agent infrastructure, runtime, and observability.
 * 
 * This stack combines:
 * - Agent Infrastructure (from agent-infra-stack.ts) - ECR repo, CodeBuild, IAM role
 * - Agent Runtime (from agent-runtime-stack.ts) - S3 deployment, build trigger, CfnRuntime
 * - Observability (from observability-stack.ts) - CloudWatch logs, X-Ray delivery
 * 
 * Exports:
 * - AgentRuntimeArn
 */

import * as cdk from 'aws-cdk-lib';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as codebuild from 'aws-cdk-lib/aws-codebuild';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as bedrockagentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import { NagSuppressions } from 'cdk-nag';
import { Construct } from 'constructs';
import { config, exportNames } from './config';
import { applyCommonSuppressions, applyBucketDeploymentSuppressions, applyCodeBuildSuppressions, applyBedrockSuppressions } from './nag-suppressions';
import * as path from 'path';

export class AgentStack extends cdk.Stack {
  // Infrastructure resources
  /** ECR repository for agent container images */
  public readonly agentRepository: ecr.Repository;
  /** S3 bucket for CodeBuild source files */
  public readonly sourceBucket: s3.Bucket;
  /** CodeBuild project for building agent Docker images */
  public readonly buildProject: codebuild.Project;
  /** IAM role for AgentCore Runtime */
  public readonly agentRuntimeRole: iam.Role;

  // Runtime resources
  /** The AgentCore CfnRuntime */
  public readonly agentRuntime: bedrockagentcore.CfnRuntime;

  // Observability resources
  /** The CloudWatch Log Group for Runtime logs */
  public readonly runtimeLogGroup: logs.LogGroup;
  /** The CloudWatch Log Group for Memory logs */
  public readonly memoryLogGroup: logs.LogGroup;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Import values from Bedrock stack
    const guardrailId = cdk.Fn.importValue(exportNames.guardrailId);
    const guardrailVersion = cdk.Fn.importValue(exportNames.guardrailVersion);
    const knowledgeBaseId = cdk.Fn.importValue(exportNames.knowledgeBaseId);
    const memoryId = cdk.Fn.importValue(exportNames.memoryId);
    const memoryArn = cdk.Fn.importValue(exportNames.memoryArn);

    // ========================================================================
    // AGENT INFRASTRUCTURE SECTION
    // Requirements: 1.4, 2.1
    // ========================================================================

    // --- ECR Repository ---
    this.agentRepository = new ecr.Repository(this, 'AgentRepository', {
      repositoryName: config.agentRepoName,
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

    // --- S3 Bucket for CodeBuild source ---
    // Import access logs bucket from Foundation stack
    const accessLogsBucketName = cdk.Fn.importValue(`${config.appName}-AccessLogsBucketName`);
    const accessLogsBucket = s3.Bucket.fromBucketName(this, 'ImportedAccessLogsBucket', accessLogsBucketName);

    this.sourceBucket = new s3.Bucket(this, 'BuildSourceBucket', {
      bucketName: `${config.buildSourceBucketName}-${this.account}-${this.region}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      serverAccessLogsBucket: accessLogsBucket,
      serverAccessLogsPrefix: 'agent-build-source/',
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

    // --- CodeBuild Role ---
    const codeBuildRole = new iam.Role(this, 'CodeBuildRole', {
      roleName: `${config.appName}-codebuild-role-${this.region}`,
      assumedBy: new iam.ServicePrincipal('codebuild.amazonaws.com'),
      description: 'CodeBuild role for building agent Docker images',
    });

    this.agentRepository.grantPullPush(codeBuildRole);
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
          `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/codebuild/${config.agentBuildProjectName}*`,
        ],
      })
    );

    // --- CodeBuild Project ---
    this.buildProject = new codebuild.Project(this, 'AgentBuildProject', {
      projectName: config.agentBuildProjectName,
      description: 'Build ARM64 Docker images for AgentCore agent',
      role: codeBuildRole,
      source: codebuild.Source.s3({
        bucket: this.sourceBucket,
        path: 'agent-source.zip',
      }),
      environment: {
        buildImage: codebuild.LinuxArmBuildImage.AMAZON_LINUX_2_STANDARD_3_0,
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
            value: this.agentRepository.repositoryUri,
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
              'docker build -t $ECR_REPO_URI:latest .',
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

    // --- Agent Runtime IAM Role ---
    this.agentRuntimeRole = new iam.Role(this, 'AgentRuntimeRole', {
      roleName: `${config.appName}-agent-runtime-role-${this.region}`,
      assumedBy: new iam.CompositePrincipal(
        new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
        new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      ),
      description: 'IAM role for AgentCore Runtime with Bedrock, ECR, and CloudWatch permissions',
    });

    // ECR permissions
    this.agentRuntimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'ECRAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'ecr:GetDownloadUrlForLayer',
          'ecr:BatchGetImage',
          'ecr:BatchCheckLayerAvailability',
          'ecr:GetAuthorizationToken',
        ],
        resources: ['*'],
      })
    );

    // CloudWatch Logs permissions
    this.agentRuntimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'CloudWatchLogsAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:CreateLogGroup',
          'logs:CreateLogStream',
          'logs:PutLogEvents',
          'logs:DescribeLogStreams',
        ],
        resources: [
          `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*`,
        ],
      })
    );

    // X-Ray tracing permissions
    this.agentRuntimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'XRayAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'xray:PutTraceSegments',
          'xray:PutTelemetryRecords',
          'xray:GetSamplingRules',
          'xray:GetSamplingTargets',
          'xray:GetSamplingStatisticSummaries',
        ],
        resources: ['*'],
      })
    );

    // Bedrock model invocation permissions
    this.agentRuntimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'BedrockModelAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:InvokeModel',
          'bedrock:InvokeModelWithResponseStream',
          'bedrock:Converse',
          'bedrock:ConverseStream',
        ],
        resources: [
          'arn:aws:bedrock:*::foundation-model/*',
          'arn:aws:bedrock:*:*:inference-profile/*',
        ],
      })
    );

    // Bedrock Guardrails permissions
    this.agentRuntimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'BedrockGuardrailAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:ApplyGuardrail',
          'bedrock:GetGuardrail',
        ],
        resources: [
          `arn:aws:bedrock:${this.region}:${this.account}:guardrail/*`,
        ],
      })
    );

    // Bedrock Knowledge Base permissions
    this.agentRuntimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'BedrockKnowledgeBaseAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:Retrieve',
          'bedrock:RetrieveAndGenerate',
        ],
        resources: [
          `arn:aws:bedrock:${this.region}:${this.account}:knowledge-base/*`,
        ],
      })
    );

    // AgentCore Memory permissions
    this.agentRuntimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'AgentCoreMemoryAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock-agentcore:GetMemory',
          'bedrock-agentcore:CreateMemory',
          'bedrock-agentcore:DeleteMemory',
          'bedrock-agentcore:ListMemories',
          'bedrock-agentcore:CreateEvent',
          'bedrock-agentcore:GetEvent',
          'bedrock-agentcore:ListEvents',
          'bedrock-agentcore:DeleteEvent',
          'bedrock-agentcore:CreateMemoryRecord',
          'bedrock-agentcore:GetMemoryRecord',
          'bedrock-agentcore:ListMemoryRecords',
          'bedrock-agentcore:DeleteMemoryRecord',
          'bedrock-agentcore:SearchMemoryRecords',
        ],
        resources: [
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:memory/*`,
        ],
      })
    );

    // ========================================================================
    // AGENT RUNTIME SECTION
    // Requirements: 1.4, 2.1
    // ========================================================================

    // --- Deploy agent source files to S3 ---
    const agentSourceDeployment = new s3deploy.BucketDeployment(this, 'AgentSourceDeployment', {
      sources: [
        s3deploy.Source.asset(path.join(__dirname, '../../agent'), {
          exclude: [
            '.venv/**',
            'venv/**',
            '__pycache__/**',
            '*.pyc',
            '.git/**',
            'node_modules/**',
            '.env',
            '.bedrock_agentcore/**',
            '.bedrock_agentcore.yaml',
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
      destinationKeyPrefix: 'agent-source',
      prune: true,
      retainOnDelete: false,
      memoryLimit: 512,
    });

    // --- Trigger CodeBuild ---
    const triggerBuild = new cr.AwsCustomResource(this, 'TriggerCodeBuild', {
      onCreate: {
        service: 'CodeBuild',
        action: 'startBuild',
        parameters: {
          projectName: this.buildProject.projectName,
          sourceTypeOverride: 'S3',
          sourceLocationOverride: `${this.sourceBucket.bucketName}/agent-source/`,
        },
        physicalResourceId: cr.PhysicalResourceId.fromResponse('build.id'),
      },
      onUpdate: {
        service: 'CodeBuild',
        action: 'startBuild',
        parameters: {
          projectName: this.buildProject.projectName,
          sourceTypeOverride: 'S3',
          sourceLocationOverride: `${this.sourceBucket.bucketName}/agent-source/`,
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

    triggerBuild.node.addDependency(agentSourceDeployment);

    // --- Build Waiter Lambda ---
    const buildWaiterFunction = new lambda.Function(this, 'BuildWaiterFunction', {
      functionName: `${config.appName}-build-waiter`,
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
      environment: {
        BUILD_PROJECT_NAME: config.agentBuildProjectName,
      },
    });

    buildWaiterFunction.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['codebuild:BatchGetBuilds'],
        resources: [this.buildProject.projectArn],
      })
    );

    const buildWaiterProviderLogGroup = new logs.LogGroup(this, 'BuildWaiterProviderLogs', {
      retention: logs.RetentionDays.ONE_DAY,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const buildWaiterProvider = new cr.Provider(this, 'BuildWaiterProvider', {
      onEventHandler: buildWaiterFunction,
      logGroup: buildWaiterProviderLogGroup,
    });

    const buildWaiter = new cdk.CustomResource(this, 'BuildWaiter', {
      serviceToken: buildWaiterProvider.serviceToken,
      properties: {
        BuildId: triggerBuild.getResponseField('build.id'),
        Timestamp: Date.now().toString(),
      },
    });

    buildWaiter.node.addDependency(triggerBuild);

    // --- CfnRuntime ---
    this.agentRuntime = new bedrockagentcore.CfnRuntime(this, 'AgentRuntime', {
      agentRuntimeName: config.agentRuntimeName,
      description: `AgentCore Runtime for ${config.appName}`,
      agentRuntimeArtifact: {
        containerConfiguration: {
          containerUri: `${this.agentRepository.repositoryUri}:latest`,
        },
      },
      networkConfiguration: {
        networkMode: 'PUBLIC',
      },
      roleArn: this.agentRuntimeRole.roleArn,
      protocolConfiguration: 'HTTP',
      environmentVariables: {
        AWS_REGION: this.region,
        LOG_LEVEL: 'INFO',
        MEMORY_ID: memoryId,
        GUARDRAIL_ID: guardrailId,
        GUARDRAIL_VERSION: guardrailVersion,
        KB_ID: knowledgeBaseId,
      },
      tags: {
        Application: config.appName,
        ManagedBy: 'CDK',
      },
    });

    this.agentRuntime.node.addDependency(buildWaiter);


    // ========================================================================
    // OBSERVABILITY SECTION
    // Requirements: 1.4, 2.1
    // ========================================================================

    // Use deterministic names based on the app name
    const runtimeId = `${config.appName}-runtime`;
    const memoryIdName = `${config.appName}-memory`;

    // --- CloudWatch Log Group for Runtime ---
    this.runtimeLogGroup = new logs.LogGroup(this, 'RuntimeLogGroup', {
      logGroupName: `/aws/vendedlogs/bedrock-agentcore/runtime/${runtimeId}`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // --- Delivery Source for Application Logs ---
    const logsDeliverySource = new logs.CfnDeliverySource(this, 'LogsDeliverySource', {
      name: `${runtimeId}-logs-source`,
      logType: 'APPLICATION_LOGS',
      resourceArn: this.agentRuntime.attrAgentRuntimeArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });

    // --- Delivery Source for Traces ---
    const tracesDeliverySource = new logs.CfnDeliverySource(this, 'TracesDeliverySource', {
      name: `${runtimeId}-traces-source`,
      logType: 'TRACES',
      resourceArn: this.agentRuntime.attrAgentRuntimeArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });

    // --- Delivery Destination for CloudWatch Logs ---
    const logsDeliveryDestination = new logs.CfnDeliveryDestination(this, 'LogsDeliveryDestination', {
      name: `${runtimeId}-logs-destination`,
      deliveryDestinationType: 'CWL',
      destinationResourceArn: this.runtimeLogGroup.logGroupArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });

    // --- Delivery Destination for X-Ray Traces ---
    const tracesDeliveryDestination = new logs.CfnDeliveryDestination(this, 'TracesDeliveryDestination', {
      name: `${runtimeId}-traces-destination`,
      deliveryDestinationType: 'XRAY',
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });

    // --- Delivery: Connect Logs Source to CloudWatch Logs Destination ---
    const logsDelivery = new logs.CfnDelivery(this, 'LogsDelivery', {
      deliverySourceName: logsDeliverySource.name,
      deliveryDestinationArn: logsDeliveryDestination.attrArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });
    logsDelivery.addDependency(logsDeliverySource);
    logsDelivery.addDependency(logsDeliveryDestination);

    // --- Delivery: Connect Traces Source to X-Ray Destination ---
    const tracesDelivery = new logs.CfnDelivery(this, 'TracesDelivery', {
      deliverySourceName: tracesDeliverySource.name,
      deliveryDestinationArn: tracesDeliveryDestination.attrArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });
    tracesDelivery.addDependency(tracesDeliverySource);
    tracesDelivery.addDependency(tracesDeliveryDestination);

    // ========================================================================
    // MEMORY OBSERVABILITY
    // ========================================================================

    // CloudWatch Log Group for Memory vended logs
    this.memoryLogGroup = new logs.LogGroup(this, 'MemoryLogGroup', {
      logGroupName: `/aws/vendedlogs/bedrock-agentcore/memory/${memoryIdName}`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Delivery Source for Memory Application Logs
    const memoryLogsDeliverySource = new logs.CfnDeliverySource(this, 'MemoryLogsDeliverySource', {
      name: `${memoryIdName}-logs-source`,
      logType: 'APPLICATION_LOGS',
      resourceArn: memoryArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });

    // Delivery Source for Memory Traces
    const memoryTracesDeliverySource = new logs.CfnDeliverySource(this, 'MemoryTracesDeliverySource', {
      name: `${memoryIdName}-traces-source`,
      logType: 'TRACES',
      resourceArn: memoryArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });

    // Delivery Destination for Memory CloudWatch Logs
    const memoryLogsDeliveryDestination = new logs.CfnDeliveryDestination(this, 'MemoryLogsDeliveryDestination', {
      name: `${memoryIdName}-logs-destination`,
      deliveryDestinationType: 'CWL',
      destinationResourceArn: this.memoryLogGroup.logGroupArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });

    // Delivery Destination for Memory X-Ray Traces
    const memoryTracesDeliveryDestination = new logs.CfnDeliveryDestination(this, 'MemoryTracesDeliveryDestination', {
      name: `${memoryIdName}-traces-destination`,
      deliveryDestinationType: 'XRAY',
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });

    // Delivery: Connect Memory Logs Source to CloudWatch Logs Destination
    const memoryLogsDelivery = new logs.CfnDelivery(this, 'MemoryLogsDelivery', {
      deliverySourceName: memoryLogsDeliverySource.name,
      deliveryDestinationArn: memoryLogsDeliveryDestination.attrArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });
    memoryLogsDelivery.addDependency(memoryLogsDeliverySource);
    memoryLogsDelivery.addDependency(memoryLogsDeliveryDestination);

    // Delivery: Connect Memory Traces Source to X-Ray Destination
    const memoryTracesDelivery = new logs.CfnDelivery(this, 'MemoryTracesDelivery', {
      deliverySourceName: memoryTracesDeliverySource.name,
      deliveryDestinationArn: memoryTracesDeliveryDestination.attrArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });
    memoryTracesDelivery.addDependency(memoryTracesDeliverySource);
    memoryTracesDelivery.addDependency(memoryTracesDeliveryDestination);

    // ========================================================================
    // Resource Policy for X-Ray Transaction Search
    // ========================================================================

    new logs.CfnResourcePolicy(this, 'XRayTracingPolicy', {
      policyName: 'AgentCoreTracingPolicy',
      policyDocument: JSON.stringify({
        Version: '2012-10-17',
        Statement: [
          {
            Sid: 'TransactionSearchXRayAccess',
            Effect: 'Allow',
            Principal: {
              Service: 'xray.amazonaws.com',
            },
            Action: 'logs:PutLogEvents',
            Resource: [
              `arn:aws:logs:${this.region}:${this.account}:log-group:aws/spans:*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/application-signals/data:*`,
            ],
            Condition: {
              ArnLike: {
                'aws:SourceArn': `arn:aws:xray:${this.region}:${this.account}:*`,
              },
              StringEquals: {
                'aws:SourceAccount': this.account,
              },
            },
          },
        ],
      }),
    });

    // ========================================================================
    // Enable X-Ray Transaction Search and Sampling (Lambda-backed custom resource)
    // ========================================================================

    const xrayConfigFunction = new lambda.Function(this, 'XRayConfigFunction', {
      functionName: `${config.appName}-xray-config`,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'index.handler',
      timeout: cdk.Duration.minutes(2),
      memorySize: 128,
      code: lambda.Code.fromInline(`
import boto3
import json
import cfnresponse

def handler(event, context):
    print(f"Event: {json.dumps(event)}")
    
    if event['RequestType'] == 'Delete':
        cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
        return
    
    try:
        xray = boto3.client('xray')
        results = {}
        
        try:
            xray.update_trace_segment_destination(Destination='CloudWatchLogs')
            results['TransactionSearch'] = 'Enabled'
        except Exception as e:
            if 'already' in str(e).lower():
                results['TransactionSearch'] = 'Already enabled'
            else:
                raise e
        
        try:
            xray.update_indexing_rule(
                Name='Default',
                Rule={'Probabilistic': {'DesiredSamplingPercentage': 100}}
            )
            results['Sampling'] = 'Set to 100%'
        except Exception as e:
            results['Sampling'] = f'Warning: {str(e)}'
        
        print(f"Results: {json.dumps(results)}")
        cfnresponse.send(event, context, cfnresponse.SUCCESS, results)
        
    except Exception as e:
        print(f"Error: {str(e)}")
        cfnresponse.send(event, context, cfnresponse.FAILED, {}, reason=str(e))
`),
    });

    // X-Ray permissions
    xrayConfigFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'TransactionSearchXRayPermissions',
        effect: iam.Effect.ALLOW,
        actions: [
          'xray:GetTraceSegmentDestination',
          'xray:UpdateTraceSegmentDestination',
          'xray:GetIndexingRules',
          'xray:UpdateIndexingRule',
        ],
        resources: ['*'],
      })
    );

    // CloudWatch Logs permissions
    xrayConfigFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'TransactionSearchLogGroupPermissions',
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:CreateLogGroup',
          'logs:CreateLogStream',
          'logs:PutRetentionPolicy',
        ],
        resources: [
          `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/application-signals/data:*`,
          `arn:aws:logs:${this.region}:${this.account}:log-group:aws/spans:*`,
        ],
      })
    );

    // Resource policy permissions
    xrayConfigFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'TransactionSearchLogsPermissions',
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:PutResourcePolicy',
          'logs:DescribeResourcePolicies',
        ],
        resources: ['*'],
      })
    );

    // Application Signals permissions
    xrayConfigFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'TransactionSearchApplicationSignalsPermissions',
        effect: iam.Effect.ALLOW,
        actions: ['application-signals:StartDiscovery'],
        resources: ['*'],
      })
    );

    // Service-linked role permissions
    xrayConfigFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'CloudWatchApplicationSignalsCreateServiceLinkedRolePermissions',
        effect: iam.Effect.ALLOW,
        actions: ['iam:CreateServiceLinkedRole'],
        resources: [
          `arn:aws:iam::${this.account}:role/aws-service-role/application-signals.cloudwatch.amazonaws.com/AWSServiceRoleForCloudWatchApplicationSignals`,
        ],
        conditions: {
          StringLike: {
            'iam:AWSServiceName': 'application-signals.cloudwatch.amazonaws.com',
          },
        },
      })
    );

    xrayConfigFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'CloudWatchApplicationSignalsGetRolePermissions',
        effect: iam.Effect.ALLOW,
        actions: ['iam:GetRole'],
        resources: [
          `arn:aws:iam::${this.account}:role/aws-service-role/application-signals.cloudwatch.amazonaws.com/AWSServiceRoleForCloudWatchApplicationSignals`,
        ],
      })
    );

    xrayConfigFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'CloudWatchApplicationSignalsCloudTrailPermissions',
        effect: iam.Effect.ALLOW,
        actions: ['cloudtrail:CreateServiceLinkedChannel'],
        resources: [
          `arn:aws:cloudtrail:${this.region}:${this.account}:channel/aws-service-channel/application-signals/*`,
        ],
      })
    );

    const xrayConfigProvider = new cr.Provider(this, 'XRayConfigProvider', {
      onEventHandler: xrayConfigFunction,
      logGroup: new logs.LogGroup(this, 'XRayConfigLogs', {
        retention: logs.RetentionDays.ONE_DAY,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });

    new cdk.CustomResource(this, 'XRayConfig', {
      serviceToken: xrayConfigProvider.serviceToken,
      properties: {
        Timestamp: Date.now().toString(),
      },
    });

    // ========================================================================
    // UPDATE SECRETS MANAGER WITH AGENT RUNTIME ARN
    // Requirements: 2.1, 2.3
    // ========================================================================
    
    // Import secret ARN from Foundation stack
    const secretArn = cdk.Fn.importValue(exportNames.secretArn);
    
    // Lambda function to merge values into existing secret
    const updateSecretFunction = new lambda.Function(this, 'UpdateSecretFunction', {
      functionName: `${config.appName}-update-secret-agent`,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'index.handler',
      timeout: cdk.Duration.minutes(1),
      memorySize: 128,
      code: lambda.Code.fromInline(`
import boto3
import json
import cfnresponse

def handler(event, context):
    print(f"Event: {json.dumps(event)}")
    
    if event['RequestType'] == 'Delete':
        cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
        return
    
    try:
        secret_id = event['ResourceProperties']['SecretId']
        new_values = json.loads(event['ResourceProperties']['NewValues'])
        
        client = boto3.client('secretsmanager')
        
        # Get existing secret
        response = client.get_secret_value(SecretId=secret_id)
        existing = json.loads(response['SecretString'])
        
        # Merge new values
        existing.update(new_values)
        
        # Update secret
        client.put_secret_value(
            SecretId=secret_id,
            SecretString=json.dumps(existing)
        )
        
        print(f"Updated secret with keys: {list(new_values.keys())}")
        cfnresponse.send(event, context, cfnresponse.SUCCESS, {'Updated': list(new_values.keys())})
        
    except Exception as e:
        print(f"Error: {str(e)}")
        cfnresponse.send(event, context, cfnresponse.FAILED, {}, reason=str(e))
`),
    });

    updateSecretFunction.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'secretsmanager:GetSecretValue',
          'secretsmanager:PutSecretValue',
        ],
        resources: [
          `arn:aws:secretsmanager:${this.region}:${this.account}:secret:${config.secretName}*`,
        ],
      })
    );

    const updateSecretProviderLogGroup = new logs.LogGroup(this, 'UpdateSecretProviderLogs', {
      retention: logs.RetentionDays.ONE_DAY,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const updateSecretProvider = new cr.Provider(this, 'UpdateSecretProvider', {
      onEventHandler: updateSecretFunction,
      logGroup: updateSecretProviderLogGroup,
    });

    const updateSecretWithAgentRuntime = new cdk.CustomResource(this, 'UpdateSecretWithAgentRuntime', {
      serviceToken: updateSecretProvider.serviceToken,
      properties: {
        SecretId: secretArn,
        NewValues: JSON.stringify({
          agentcore_runtime_arn: this.agentRuntime.attrAgentRuntimeArn,
        }),
        Timestamp: Date.now().toString(),
      },
    });

    // Ensure secret update happens after runtime is created
    updateSecretWithAgentRuntime.node.addDependency(this.agentRuntime);

    // ========================================================================
    // STACK OUTPUTS AND EXPORTS
    // Requirements: 2.3
    // ========================================================================

    // --- Agent Runtime Export (for ChatApp stack) ---
    new cdk.CfnOutput(this, 'AgentRuntimeArn', {
      value: this.agentRuntime.attrAgentRuntimeArn,
      description: 'AgentCore Runtime ARN',
      exportName: exportNames.agentRuntimeArn,
    });

    // --- Additional outputs (not exported) ---
    new cdk.CfnOutput(this, 'AgentRuntimeId', {
      value: this.agentRuntime.attrAgentRuntimeId,
      description: 'AgentCore Runtime ID',
    });

    new cdk.CfnOutput(this, 'AgentRuntimeVersion', {
      value: this.agentRuntime.attrAgentRuntimeVersion,
      description: 'AgentCore Runtime Version',
    });

    new cdk.CfnOutput(this, 'AgentRepositoryUri', {
      value: this.agentRepository.repositoryUri,
      description: 'ECR repository URI for agent container images',
    });

    new cdk.CfnOutput(this, 'BuildSourceBucketName', {
      value: this.sourceBucket.bucketName,
      description: 'S3 bucket name for CodeBuild source files',
    });

    new cdk.CfnOutput(this, 'BuildProjectName', {
      value: this.buildProject.projectName,
      description: 'CodeBuild project name for agent builds',
    });

    new cdk.CfnOutput(this, 'RuntimeLogGroupArn', {
      value: this.runtimeLogGroup.logGroupArn,
      description: 'CloudWatch Log Group ARN for Runtime logs',
    });

    new cdk.CfnOutput(this, 'RuntimeLogGroupName', {
      value: this.runtimeLogGroup.logGroupName!,
      description: 'CloudWatch Log Group name for Runtime logs',
    });

    new cdk.CfnOutput(this, 'MemoryLogGroupArn', {
      value: this.memoryLogGroup.logGroupArn,
      description: 'CloudWatch Log Group ARN for Memory logs',
    });

    new cdk.CfnOutput(this, 'MemoryLogGroupName', {
      value: this.memoryLogGroup.logGroupName!,
      description: 'CloudWatch Log Group name for Memory logs',
    });

    new cdk.CfnOutput(this, 'GenAIDashboardUrl', {
      value: `https://${this.region}.console.aws.amazon.com/cloudwatch/home?region=${this.region}#gen-ai-observability/agent-core/agents`,
      description: 'GenAI Observability Dashboard URL',
    });

    new cdk.CfnOutput(this, 'XRayTracesUrl', {
      value: `https://${this.region}.console.aws.amazon.com/cloudwatch/home?region=${this.region}#xray:service-map`,
      description: 'X-Ray Service Map URL',
    });

    // ========================================================================
    // CDK-NAG SUPPRESSIONS
    // ========================================================================
    
    applyCommonSuppressions(this);
    applyBucketDeploymentSuppressions(this);
    applyCodeBuildSuppressions(this);
    applyBedrockSuppressions(this);

    // Suppress ECR authorization token wildcard (required by ECR)
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Agent/AgentRuntimeRole/DefaultPolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'ECR GetAuthorizationToken requires Resource::* as it is account-level, not repository-specific.',
          appliesTo: ['Resource::*'],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'AgentCore Runtime logs require wildcard for dynamic log group names.',
          appliesTo: [`Resource::arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*`],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'Bedrock Guardrail ID is dynamic. Scoped to guardrail resources only.',
          appliesTo: [`Resource::arn:aws:bedrock:${this.region}:${this.account}:guardrail/*`],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'Bedrock Knowledge Base ID is dynamic. Scoped to knowledge-base resources only.',
          appliesTo: [`Resource::arn:aws:bedrock:${this.region}:${this.account}:knowledge-base/*`],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'AgentCore Memory ID is dynamic. Scoped to memory resources only.',
          appliesTo: [`Resource::arn:aws:bedrock-agentcore:${this.region}:${this.account}:memory/*`],
        },
      ]
    );

    // Suppress CodeBuild role wildcards
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Agent/CodeBuildRole/DefaultPolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'CodeBuild log groups include build number. Scoped to specific project prefix.',
          appliesTo: [
            `Resource::arn:aws:logs:${this.region}:${this.account}:log-group:/aws/codebuild/${config.agentBuildProjectName}*`,
            `Resource::arn:aws:logs:${this.region}:${this.account}:log-group:/aws/codebuild/<AgentBuildProject0299660E>:*`,
          ],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'CodeBuild report groups include dynamic names. Scoped to specific project.',
          appliesTo: [`Resource::arn:aws:codebuild:${this.region}:${this.account}:report-group/<AgentBuildProject0299660E>-*`],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'CodeBuild needs access to all objects in source bucket.',
          appliesTo: ['Resource::<BuildSourceBucketB61842F6.Arn>/*'],
        },
      ]
    );

    // Suppress BucketDeployment wildcards
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Agent/Custom::CDKBucketDeployment8693BB64968944B69AAFB0CC9EB8756C512MiB/ServiceRole/DefaultPolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'BucketDeployment needs access to CDK assets bucket for deployment.',
          appliesTo: [`Resource::arn:aws:s3:::cdk-hnb659fds-assets-${this.account}-${this.region}/*`],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'BucketDeployment needs access to all objects in destination bucket.',
          appliesTo: ['Resource::<BuildSourceBucketB61842F6.Arn>/*'],
        },
      ]
    );

    // Suppress provider framework wildcards
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Agent/BuildWaiterProvider/framework-onEvent/ServiceRole/DefaultPolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'CDK Provider framework requires lambda:InvokeFunction with wildcard for versioned invocations.',
          appliesTo: ['Resource::<BuildWaiterFunction2EBEED87.Arn>:*'],
        },
      ]
    );

    // Suppress XRay config function wildcards
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Agent/XRayConfigFunction/ServiceRole/DefaultPolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'X-Ray configuration requires account-level permissions for trace settings.',
          appliesTo: ['Resource::*'],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'Application Signals log groups are AWS-managed with fixed names.',
          appliesTo: [
            `Resource::arn:aws:logs:${this.region}:${this.account}:log-group:/aws/application-signals/data:*`,
            `Resource::arn:aws:logs:${this.region}:${this.account}:log-group:aws/spans:*`,
          ],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'CloudTrail channel for Application Signals requires wildcard.',
          appliesTo: [`Resource::arn:aws:cloudtrail:${this.region}:${this.account}:channel/aws-service-channel/application-signals/*`],
        },
      ]
    );

    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Agent/XRayConfigProvider/framework-onEvent/ServiceRole/DefaultPolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'CDK Provider framework requires lambda:InvokeFunction with wildcard for versioned invocations.',
          appliesTo: ['Resource::<XRayConfigFunctionCF1D2705.Arn>:*'],
        },
      ]
    );

    // Suppress update secret function wildcards
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Agent/UpdateSecretFunction/ServiceRole/DefaultPolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'Secret ARN includes random suffix. Scoped to specific secret name prefix.',
          appliesTo: [`Resource::arn:aws:secretsmanager:${this.region}:${this.account}:secret:${config.secretName}*`],
        },
      ]
    );

    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Agent/UpdateSecretProvider/framework-onEvent/ServiceRole/DefaultPolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'CDK Provider framework requires lambda:InvokeFunction with wildcard for versioned invocations.',
          appliesTo: ['Resource::<UpdateSecretFunction83556651.Arn>:*'],
        },
      ]
    );
  }
}
