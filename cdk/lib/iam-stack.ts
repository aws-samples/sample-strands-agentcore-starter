/**
 * IAM Stack - ECS task roles and execution roles.
 * 
 * This stack creates:
 * - ECS task execution role with ECR, CloudWatch Logs, and Secrets Manager access
 * - ECS task role with permissions for AgentCore, Cognito, DynamoDB, Bedrock Guardrails, and Knowledge Base
 * - ECS infrastructure role for Express Mode services
 * 
 * Exports:
 * - ExecutionRoleArn
 * - TaskRoleArn
 * - InfrastructureRoleArn
 */

import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import { config, exportNames } from './config';

export class IamStack extends cdk.Stack {
  /** ECS task execution role */
  public readonly executionRole: iam.Role;
  
  /** ECS task role */
  public readonly taskRole: iam.Role;
  
  /** ECS infrastructure role for Express Mode */
  public readonly infrastructureRole: iam.Role;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ========================================================================
    // Task 7.1: Create task execution role
    // Requirements: 6.1
    // ========================================================================
    
    // Create ECS task execution role with trust policy for ECS tasks
    this.executionRole = new iam.Role(this, 'TaskExecutionRole', {
      roleName: `${config.appName}-ecs-execution-role`,
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      description: 'ECS task execution role for pulling images and writing logs',
    });

    // Attach AmazonECSTaskExecutionRolePolicy managed policy
    this.executionRole.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy')
    );

    // Add inline policy for Secrets Manager access
    this.executionRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'SecretsManagerAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'secretsmanager:GetSecretValue',
          'secretsmanager:DescribeSecret',
        ],
        resources: [
          `arn:aws:secretsmanager:${this.region}:${this.account}:secret:${config.secretName}*`,
        ],
      })
    );

    // ========================================================================
    // Task 7.2: Create task role
    // Requirements: 6.2, 6.4
    // ========================================================================
    
    // Create ECS task role with trust policy for ECS tasks
    this.taskRole = new iam.Role(this, 'TaskRole', {
      roleName: `${config.appName}-ecs-task-role`,
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      description: 'ECS task role with permissions for AgentCore, Cognito, DynamoDB, Bedrock',
    });

    // Import table ARNs from Storage stack using Fn.importValue
    const usageTableArn = cdk.Fn.importValue(exportNames.usageTableArn);
    const feedbackTableArn = cdk.Fn.importValue(exportNames.feedbackTableArn);
    const guardrailTableArn = cdk.Fn.importValue(exportNames.guardrailTableArn);
    const promptTemplatesTableArn = cdk.Fn.importValue(exportNames.promptTemplatesTableArn);

    // Import Cognito User Pool ARN from Auth stack
    const userPoolArn = cdk.Fn.importValue(exportNames.userPoolArn);

    // Import Guardrail ARN from Guardrail stack
    const guardrailArn = cdk.Fn.importValue(exportNames.guardrailArn);

    // Import Knowledge Base ARN from KnowledgeBase stack
    const knowledgeBaseArn = cdk.Fn.importValue(exportNames.knowledgeBaseArn);

    // AgentCore Runtime permissions
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'AgentCoreRuntimeAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock-agentcore:InvokeAgent',
          'bedrock-agentcore:InvokeAgentRuntime',
          'bedrock-agentcore:InvokeAgentWithResponseStream',
        ],
        resources: ['*'],
      })
    );

    // AgentCore Memory permissions (for chatapp memory viewer)
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'AgentCoreMemoryAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          // Memory management
          'bedrock-agentcore:GetMemory',
          'bedrock-agentcore:ListMemories',
          // Event operations (short-term memory)
          'bedrock-agentcore:ListEvents',
          'bedrock-agentcore:GetEvent',
          // Memory record operations (long-term/semantic memory)
          'bedrock-agentcore:ListMemoryRecords',
          'bedrock-agentcore:GetMemoryRecord',
          'bedrock-agentcore:SearchMemoryRecords',
        ],
        resources: [
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:memory/*`,
        ],
      })
    );

    // Cognito permissions (resource-specific)
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'CognitoAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'cognito-idp:AdminGetUser',
          'cognito-idp:AdminCreateUser',
          'cognito-idp:AdminSetUserPassword',
          'cognito-idp:AdminInitiateAuth',
          'cognito-idp:AdminRespondToAuthChallenge',
          'cognito-idp:AdminListGroupsForUser',
          'cognito-idp:ListUsers',
          'cognito-idp:ListGroups',
          'cognito-idp:DescribeUserPool',
        ],
        resources: [userPoolArn],
      })
    );

    // DynamoDB permissions (resource-specific using imported ARNs)
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'DynamoDBAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'dynamodb:GetItem',
          'dynamodb:PutItem',
          'dynamodb:UpdateItem',
          'dynamodb:DeleteItem',
          'dynamodb:Query',
          'dynamodb:Scan',
          'dynamodb:BatchGetItem',
          'dynamodb:BatchWriteItem',
        ],
        resources: [
          usageTableArn,
          `${usageTableArn}/index/*`,
          feedbackTableArn,
          `${feedbackTableArn}/index/*`,
          guardrailTableArn,
          `${guardrailTableArn}/index/*`,
          promptTemplatesTableArn,
          `${promptTemplatesTableArn}/index/*`,
        ],
      })
    );

    // Bedrock Guardrails permissions (resource-specific)
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'BedrockGuardrailAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:ApplyGuardrail',
          'bedrock:GetGuardrail',
        ],
        resources: [guardrailArn],
      })
    );

    // Bedrock Knowledge Base permissions (resource-specific)
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'BedrockKnowledgeBaseAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:Retrieve',
          'bedrock:RetrieveAndGenerate',
        ],
        resources: [knowledgeBaseArn],
      })
    );

    // Bedrock model invocation (required for KB retrieve and generate)
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'BedrockModelAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:InvokeModel',
          'bedrock:InvokeModelWithResponseStream',
        ],
        resources: [
          `arn:aws:bedrock:${this.region}::foundation-model/*`,
        ],
      })
    );

    // CloudWatch Logs permissions for application logging
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'CloudWatchLogsAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:CreateLogStream',
          'logs:PutLogEvents',
          'logs:DescribeLogStreams',
        ],
        resources: [
          `arn:aws:logs:${this.region}:${this.account}:log-group:/ecs/${config.appName}*`,
        ],
      })
    );

    // ========================================================================
    // Task 7.3: Create infrastructure role for Express Mode
    // Requirements: 6.3
    // ========================================================================
    
    // Create ECS infrastructure role for Express Mode services
    this.infrastructureRole = new iam.Role(this, 'InfrastructureRole', {
      roleName: `${config.appName}-ecs-infrastructure-role`,
      assumedBy: new iam.ServicePrincipal('ecs.amazonaws.com'),
      description: 'ECS infrastructure role for Express Mode services',
    });

    // Attach AmazonECSInfrastructureRoleforExpressGatewayServices managed policy
    this.infrastructureRole.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSInfrastructureRoleforExpressGatewayServices')
    );

    // ========================================================================
    // Task 7.4: Add stack outputs and exports
    // Requirements: 6.5
    // ========================================================================
    
    // Export execution role ARN
    new cdk.CfnOutput(this, 'ExecutionRoleArn', {
      value: this.executionRole.roleArn,
      description: 'ECS task execution role ARN',
      exportName: exportNames.executionRoleArn,
    });

    // Export task role ARN
    new cdk.CfnOutput(this, 'TaskRoleArn', {
      value: this.taskRole.roleArn,
      description: 'ECS task role ARN',
      exportName: exportNames.taskRoleArn,
    });

    // Export infrastructure role ARN
    new cdk.CfnOutput(this, 'InfrastructureRoleArn', {
      value: this.infrastructureRole.roleArn,
      description: 'ECS infrastructure role ARN for Express Mode',
      exportName: exportNames.infrastructureRoleArn,
    });
  }
}
