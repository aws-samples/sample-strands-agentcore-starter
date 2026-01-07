/**
 * CDK-Nag Suppressions - Centralized suppression rules for cdk-nag findings.
 * 
 * This file contains suppression rules for findings that are:
 * 1. CDK-generated resources (custom resources, providers, bucket deployments)
 * 2. AWS-managed policies required by services (ECS, Lambda)
 * 3. Acceptable patterns for a starter kit / PoC application
 */

import { NagSuppressions } from 'cdk-nag';
import * as cdk from 'aws-cdk-lib';

/**
 * Apply stack-level suppressions for common CDK-generated patterns.
 * Call this at the end of each stack's constructor.
 */
export function applyCommonSuppressions(stack: cdk.Stack): void {
  // Suppress Lambda runtime warnings for CDK-generated custom resources
  // These are managed by CDK and will be updated in future CDK versions
  NagSuppressions.addStackSuppressions(stack, [
    {
      id: 'AwsSolutions-L1',
      reason: 'Lambda runtime is managed by CDK for custom resources and providers. CDK will update these in future versions.',
    },
  ]);

  // Suppress AWS managed policy warnings for Lambda basic execution role
  // This is the standard pattern for Lambda functions
  NagSuppressions.addStackSuppressions(stack, [
    {
      id: 'AwsSolutions-IAM4',
      reason: 'AWSLambdaBasicExecutionRole is the standard managed policy for Lambda functions. It provides minimal CloudWatch Logs permissions.',
      appliesTo: [
        'Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole',
      ],
    },
  ]);

  // Suppress wildcard warnings for LogRetention custom resource
  // This is a CDK-managed resource for setting log retention policies
  NagSuppressions.addStackSuppressions(stack, [
    {
      id: 'AwsSolutions-IAM5',
      reason: 'LogRetention custom resource requires wildcard permissions to manage log groups across the account. This is CDK-managed.',
      appliesTo: ['Resource::*'],
    },
  ]);
}

/**
 * Apply suppressions for S3 bucket deployment patterns.
 * CDK BucketDeployment uses Lambda with S3 permissions.
 */
export function applyBucketDeploymentSuppressions(stack: cdk.Stack): void {
  NagSuppressions.addStackSuppressions(stack, [
    {
      id: 'AwsSolutions-IAM5',
      reason: 'BucketDeployment Lambda requires S3 wildcard actions (GetBucket*, GetObject*, List*, Abort*, DeleteObject*) to sync files. Scoped to specific buckets.',
      appliesTo: [
        'Action::s3:GetBucket*',
        'Action::s3:GetObject*',
        'Action::s3:List*',
        'Action::s3:Abort*',
        'Action::s3:DeleteObject*',
      ],
    },
  ]);

  // Suppress wildcards for bucket resource ARNs (objects within buckets)
  NagSuppressions.addStackSuppressions(stack, [
    {
      id: 'AwsSolutions-IAM5',
      reason: 'BucketDeployment requires access to all objects within source and destination buckets. Bucket ARN/* pattern is required for object-level operations.',
      appliesTo: [
        { regex: '/^Resource::arn:aws:s3:::cdk-.*-assets-.*\\/\\*$/g' },
        { regex: '/^Resource::<.*Bucket.*\\.Arn>\\/\\*$/g' },
      ],
    },
  ]);
}

/**
 * Apply suppressions for CodeBuild patterns.
 */
export function applyCodeBuildSuppressions(stack: cdk.Stack): void {
  // CodeBuild S3 permissions
  NagSuppressions.addStackSuppressions(stack, [
    {
      id: 'AwsSolutions-IAM5',
      reason: 'CodeBuild requires S3 wildcard actions to read source files. Permissions are scoped to specific source buckets.',
      appliesTo: [
        'Action::s3:GetBucket*',
        'Action::s3:GetObject*',
        'Action::s3:List*',
      ],
    },
  ]);

  // CodeBuild KMS encryption - acceptable for starter kit
  NagSuppressions.addStackSuppressions(stack, [
    {
      id: 'AwsSolutions-CB4',
      reason: 'CodeBuild uses AWS-managed encryption by default. KMS CMK encryption is optional for a starter kit / PoC.',
    },
  ]);

  // CodeBuild log group wildcards - required for log stream naming
  NagSuppressions.addStackSuppressions(stack, [
    {
      id: 'AwsSolutions-IAM5',
      reason: 'CodeBuild log groups require wildcard suffix for log stream names which include build IDs.',
      appliesTo: [
        { regex: '/^Resource::arn:aws:logs:.*:log-group:/aws/codebuild/.*\\*$/g' },
        { regex: '/^Resource::arn:aws:logs:.*:log-group:<.*>:\\*$/g' },
        { regex: '/^Resource::arn:aws:codebuild:.*:report-group/<.*>-\\*$/g' },
      ],
    },
  ]);
}

/**
 * Apply suppressions for ECS-related patterns.
 */
export function applyEcsSuppressions(stack: cdk.Stack): void {
  NagSuppressions.addStackSuppressions(stack, [
    {
      id: 'AwsSolutions-IAM4',
      reason: 'ECS task execution role requires AmazonECSTaskExecutionRolePolicy for pulling images and writing logs. This is AWS-managed and well-scoped.',
      appliesTo: [
        'Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy',
      ],
    },
    {
      id: 'AwsSolutions-IAM4',
      reason: 'ECS Express Mode requires AmazonECSInfrastructureRoleforExpressGatewayServices. This is AWS-managed for Express Mode services.',
      appliesTo: [
        'Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices',
      ],
    },
  ]);
}

/**
 * Apply suppressions for Secrets Manager patterns.
 */
export function applySecretsManagerSuppressions(stack: cdk.Stack): void {
  NagSuppressions.addStackSuppressions(stack, [
    {
      id: 'AwsSolutions-SMG4',
      reason: 'Application configuration secrets contain static values (IDs, ARNs, table names) that do not require rotation. These are not credentials.',
    },
  ]);
}

/**
 * Apply suppressions for Bedrock and AgentCore patterns.
 */
export function applyBedrockSuppressions(stack: cdk.Stack): void {
  NagSuppressions.addStackSuppressions(stack, [
    {
      id: 'AwsSolutions-IAM5',
      reason: 'Bedrock foundation models require wildcard resource patterns as model IDs are dynamic. Scoped to bedrock:InvokeModel actions only.',
      appliesTo: [
        'Resource::arn:aws:bedrock:*::foundation-model/*',
        'Resource::arn:aws:bedrock:*:*:inference-profile/*',
      ],
    },
  ]);
}

/**
 * Apply suppressions for CDK custom resource providers.
 * These are CDK-managed Lambda functions for custom resources.
 */
export function applyCustomResourceSuppressions(stack: cdk.Stack): void {
  // Provider framework Lambda invoke permissions
  NagSuppressions.addStackSuppressions(stack, [
    {
      id: 'AwsSolutions-IAM5',
      reason: 'CDK Provider framework requires lambda:InvokeFunction with :* suffix for version/alias invocations. This is CDK-managed.',
      appliesTo: [
        { regex: '/^Resource::<.*Function.*\\.Arn>:\\*$/g' },
      ],
    },
  ]);
}
