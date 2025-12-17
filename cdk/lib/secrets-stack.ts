/**
 * Secrets Stack - Secrets Manager for application configuration.
 * 
 * This stack creates:
 * - Secrets Manager secret with all application configuration
 * - Custom resource to retrieve Cognito client secret
 * - IAM access for ECS execution role
 * 
 * Exports:
 * - SecretArn
 */

import * as cdk from 'aws-cdk-lib';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as cr from 'aws-cdk-lib/custom-resources';
import { Construct } from 'constructs';
import { config, exportNames } from './config';

export class SecretsStack extends cdk.Stack {
  /** The Secrets Manager secret */
  public readonly secret: secretsmanager.Secret;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ========================================================================
    // Task 11.1: Create Secrets Manager secret with all required values
    // Requirements: 7.1, 7.2
    // ========================================================================

    // Import values from Auth stack
    const userPoolId = cdk.Fn.importValue(exportNames.userPoolId);
    const userPoolClientId = cdk.Fn.importValue(exportNames.userPoolClientId);

    // Import values from Storage stack
    const usageTableName = cdk.Fn.importValue(exportNames.usageTableName);
    const feedbackTableName = cdk.Fn.importValue(exportNames.feedbackTableName);
    const guardrailTableName = cdk.Fn.importValue(exportNames.guardrailTableName);
    const promptTemplatesTableName = cdk.Fn.importValue(exportNames.promptTemplatesTableName);

    // Import values from Guardrail stack
    const guardrailId = cdk.Fn.importValue(exportNames.guardrailId);
    const guardrailVersion = cdk.Fn.importValue(exportNames.guardrailVersion);

    // Import values from KnowledgeBase stack
    const knowledgeBaseId = cdk.Fn.importValue(exportNames.knowledgeBaseId);

    // Import values from AgentRuntime stack
    const agentRuntimeArn = cdk.Fn.importValue(exportNames.agentRuntimeArn);

    // Import values from Memory stack
    const memoryId = cdk.Fn.importValue(exportNames.memoryId);

    // Custom resource to retrieve Cognito User Pool Client secret
    // The client secret is not directly exportable from CloudFormation
    const getCognitoClientSecret = new cr.AwsCustomResource(this, 'GetCognitoClientSecret', {
      onCreate: {
        service: 'CognitoIdentityServiceProvider',
        action: 'describeUserPoolClient',
        parameters: {
          UserPoolId: userPoolId,
          ClientId: userPoolClientId,
        },
        physicalResourceId: cr.PhysicalResourceId.of('CognitoClientSecret'),
      },
      onUpdate: {
        service: 'CognitoIdentityServiceProvider',
        action: 'describeUserPoolClient',
        parameters: {
          UserPoolId: userPoolId,
          ClientId: userPoolClientId,
        },
        physicalResourceId: cr.PhysicalResourceId.of('CognitoClientSecret'),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['cognito-idp:DescribeUserPoolClient'],
          resources: [`arn:aws:cognito-idp:${this.region}:${this.account}:userpool/*`],
        }),
      ]),
    });

    // Get the client secret from the custom resource response
    const cognitoClientSecret = getCognitoClientSecret.getResponseField('UserPoolClient.ClientSecret');

    // Create the Secrets Manager secret with all application configuration
    this.secret = new secretsmanager.Secret(this, 'AppConfigSecret', {
      secretName: config.secretName,
      description: 'Application configuration for AgentCore Chat Application',
      
      // Secret value with all required configuration (Requirement 7.2)
      secretObjectValue: {
        // Cognito credentials
        cognito_user_pool_id: cdk.SecretValue.unsafePlainText(userPoolId.toString()),
        cognito_client_id: cdk.SecretValue.unsafePlainText(userPoolClientId.toString()),
        cognito_client_secret: cdk.SecretValue.unsafePlainText(cognitoClientSecret),
        
        // AgentCore configuration
        agentcore_runtime_arn: cdk.SecretValue.unsafePlainText(agentRuntimeArn.toString()),
        memory_id: cdk.SecretValue.unsafePlainText(memoryId.toString()),
        
        // AWS configuration
        aws_region: cdk.SecretValue.unsafePlainText(this.region),
        app_url: cdk.SecretValue.unsafePlainText(''),  // Will be updated after ChatApp deployment
        
        // DynamoDB table names
        usage_table_name: cdk.SecretValue.unsafePlainText(usageTableName.toString()),
        feedback_table_name: cdk.SecretValue.unsafePlainText(feedbackTableName.toString()),
        guardrail_table_name: cdk.SecretValue.unsafePlainText(guardrailTableName.toString()),
        prompt_templates_table_name: cdk.SecretValue.unsafePlainText(promptTemplatesTableName.toString()),
        
        // Bedrock configuration
        guardrail_id: cdk.SecretValue.unsafePlainText(guardrailId.toString()),
        guardrail_version: cdk.SecretValue.unsafePlainText(guardrailVersion.toString()),
        kb_id: cdk.SecretValue.unsafePlainText(knowledgeBaseId.toString()),
      },
      
      // Clean deletion (Requirement 13.6 - forceDeleteWithoutRecovery equivalent)
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Ensure secret is created after we have the Cognito client secret
    this.secret.node.addDependency(getCognitoClientSecret);

    // ========================================================================
    // Task 11.2: Configure IAM access for execution role
    // Requirements: 7.3
    // ========================================================================

    // Import execution role ARN from IAM stack
    const executionRoleArn = cdk.Fn.importValue(exportNames.executionRoleArn);

    // Create a resource-based policy to grant the execution role access to the secret
    // Note: The IAM stack already has an inline policy for Secrets Manager access
    // This adds a resource policy on the secret itself for defense in depth
    this.secret.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: 'AllowECSExecutionRoleAccess',
        effect: iam.Effect.ALLOW,
        principals: [new iam.ArnPrincipal(executionRoleArn.toString())],
        actions: [
          'secretsmanager:GetSecretValue',
          'secretsmanager:DescribeSecret',
        ],
        resources: ['*'],
      })
    );

    // ========================================================================
    // Task 11.3: Add stack outputs and exports
    // Requirements: 7.4
    // ========================================================================

    // Export Secret ARN
    new cdk.CfnOutput(this, 'SecretArn', {
      value: this.secret.secretArn,
      description: 'Secrets Manager secret ARN',
      exportName: exportNames.secretArn,
    });

    // Output secret name for reference
    new cdk.CfnOutput(this, 'SecretName', {
      value: this.secret.secretName,
      description: 'Secrets Manager secret name',
    });
  }
}
