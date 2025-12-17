/**
 * Agent Infrastructure Stack - ECR repository, CodeBuild project, and Agent IAM role.
 * 
 * This stack creates:
 * - ECR repository for agent container images with lifecycle rules
 * - S3 bucket for CodeBuild source files
 * - CodeBuild project for building ARM64 Docker images
 * - IAM role for AgentCore Runtime with Bedrock, ECR, and CloudWatch permissions
 * 
 * Exports:
 * - AgentRepositoryUri
 * - BuildSourceBucketName
 * - BuildProjectName
 * - BuildProjectArn
 * - AgentRuntimeRoleArn
 */

import * as cdk from 'aws-cdk-lib';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as codebuild from 'aws-cdk-lib/aws-codebuild';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import { config, exportNames } from './config';

export class AgentInfraStack extends cdk.Stack {
  /** ECR repository for agent container images */
  public readonly agentRepository: ecr.Repository;
  
  /** S3 bucket for CodeBuild source files */
  public readonly sourceBucket: s3.Bucket;
  
  /** CodeBuild project for building agent Docker images */
  public readonly buildProject: codebuild.Project;
  
  /** IAM role for AgentCore Runtime */
  public readonly agentRuntimeRole: iam.Role;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ========================================================================
    // Task 9.1: Create ECR repository for agent container images
    // Requirements: 11.1
    // ========================================================================
    
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

    // ========================================================================
    // Task 9.2: Create S3 bucket for CodeBuild source files
    // Requirements: 11.2
    // ========================================================================
    
    this.sourceBucket = new s3.Bucket(this, 'BuildSourceBucket', {
      bucketName: `${config.buildSourceBucketName}-${this.account}-${this.region}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      lifecycleRules: [
        {
          id: 'ExpireOldObjects',
          enabled: true,
          expiration: cdk.Duration.days(7),
        },
      ],
    });


    // ========================================================================
    // Task 9.3: Create CodeBuild project for ARM64 Docker builds
    // Requirements: 11.3
    // ========================================================================
    
    // Create CodeBuild service role
    const codeBuildRole = new iam.Role(this, 'CodeBuildRole', {
      roleName: `${config.appName}-codebuild-role`,
      assumedBy: new iam.ServicePrincipal('codebuild.amazonaws.com'),
      description: 'CodeBuild role for building agent Docker images',
    });

    // Grant CodeBuild permissions to push to ECR
    this.agentRepository.grantPullPush(codeBuildRole);

    // Grant CodeBuild permissions to read from S3 source bucket
    this.sourceBucket.grantRead(codeBuildRole);

    // Add CloudWatch Logs permissions for CodeBuild
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

    // Create CodeBuild project for ARM64 builds
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
        privileged: true, // Required for Docker builds
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


    // ========================================================================
    // Task 9.4: Create IAM role for AgentCore Runtime
    // Requirements: 11.4
    // ========================================================================
    
    this.agentRuntimeRole = new iam.Role(this, 'AgentRuntimeRole', {
      roleName: `${config.appName}-agent-runtime-role`,
      assumedBy: new iam.CompositePrincipal(
        new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
        new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      ),
      description: 'IAM role for AgentCore Runtime with Bedrock, ECR, and CloudWatch permissions',
    });

    // ECR permissions for pulling agent images
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
    // Per AWS docs: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/iam-permissions-on-demand.html
    // Uses wildcards for cross-region model access
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
          // Foundation models (all regions)
          'arn:aws:bedrock:*::foundation-model/*',
          // Inference profiles (all regions and accounts)
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
          // Memory management
          'bedrock-agentcore:GetMemory',
          'bedrock-agentcore:CreateMemory',
          'bedrock-agentcore:DeleteMemory',
          'bedrock-agentcore:ListMemories',
          // Event operations (short-term memory)
          'bedrock-agentcore:CreateEvent',
          'bedrock-agentcore:GetEvent',
          'bedrock-agentcore:ListEvents',
          'bedrock-agentcore:DeleteEvent',
          // Memory record operations (long-term memory)
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
    // Task 9.5: Add stack outputs and exports
    // Requirements: 11.5
    // ========================================================================
    
    // Export ECR repository URI
    new cdk.CfnOutput(this, 'AgentRepositoryUri', {
      value: this.agentRepository.repositoryUri,
      description: 'ECR repository URI for agent container images',
      exportName: exportNames.agentRepositoryUri,
    });

    // Export S3 source bucket name
    new cdk.CfnOutput(this, 'BuildSourceBucketName', {
      value: this.sourceBucket.bucketName,
      description: 'S3 bucket name for CodeBuild source files',
      exportName: exportNames.buildSourceBucketName,
    });

    // Export CodeBuild project name
    new cdk.CfnOutput(this, 'BuildProjectName', {
      value: this.buildProject.projectName,
      description: 'CodeBuild project name for agent builds',
      exportName: exportNames.buildProjectName,
    });

    // Export CodeBuild project ARN
    new cdk.CfnOutput(this, 'BuildProjectArn', {
      value: this.buildProject.projectArn,
      description: 'CodeBuild project ARN for agent builds',
      exportName: exportNames.buildProjectArn,
    });

    // Export Agent Runtime role ARN
    new cdk.CfnOutput(this, 'AgentRuntimeRoleArn', {
      value: this.agentRuntimeRole.roleArn,
      description: 'IAM role ARN for AgentCore Runtime',
      exportName: exportNames.agentRuntimeRoleArn,
    });
  }
}
