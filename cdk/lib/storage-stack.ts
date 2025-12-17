/**
 * Storage Stack - DynamoDB tables for application data.
 * 
 * This stack creates DynamoDB tables for:
 * - Usage records (user activity tracking)
 * - Feedback (user feedback on responses)
 * - Guardrail violations (content filtering violations)
 * - Prompt templates (admin-managed prompt templates)
 * 
 * All tables use PAY_PER_REQUEST billing and RemovalPolicy.DESTROY
 * for clean deletion.
 * 
 * Exports:
 * - UsageTableName / UsageTableArn
 * - FeedbackTableName / FeedbackTableArn
 * - GuardrailTableName / GuardrailTableArn
 * - PromptTemplatesTableName / PromptTemplatesTableArn
 */

import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import { config, exportNames } from './config';

export class StorageStack extends cdk.Stack {
  /** Usage records table */
  public readonly usageTable: dynamodb.Table;
  
  /** Feedback table */
  public readonly feedbackTable: dynamodb.Table;
  
  /** Guardrail violations table */
  public readonly guardrailTable: dynamodb.Table;
  
  /** Prompt templates table */
  public readonly promptTemplatesTable: dynamodb.Table;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ========================================================================
    // Task 3.1: Create usage records table
    // Requirements: 3.1, 3.5, 3.6
    // ========================================================================
    
    this.usageTable = new dynamodb.Table(this, 'UsageTable', {
      tableName: config.usageTableName,
      
      // Partition key: user_id (Requirement 3.1)
      partitionKey: {
        name: 'user_id',
        type: dynamodb.AttributeType.STRING,
      },
      
      // Sort key: timestamp (Requirement 3.1)
      sortKey: {
        name: 'timestamp',
        type: dynamodb.AttributeType.STRING,
      },
      
      // PAY_PER_REQUEST billing (Requirement 3.5)
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      
      // Clean deletion (Requirement 3.6)
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Add session-index GSI (Requirement 3.1)
    this.usageTable.addGlobalSecondaryIndex({
      indexName: 'session-index',
      partitionKey: {
        name: 'session_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'timestamp',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ========================================================================
    // Task 3.2: Add feedback table
    // Requirements: 3.2, 3.5, 3.6
    // ========================================================================
    
    this.feedbackTable = new dynamodb.Table(this, 'FeedbackTable', {
      tableName: config.feedbackTableName,
      
      // Same schema as usage records table (Requirement 3.2)
      partitionKey: {
        name: 'user_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'timestamp',
        type: dynamodb.AttributeType.STRING,
      },
      
      // PAY_PER_REQUEST billing (Requirement 3.5)
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      
      // Clean deletion (Requirement 3.6)
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Add session-index GSI (Requirement 3.2)
    this.feedbackTable.addGlobalSecondaryIndex({
      indexName: 'session-index',
      partitionKey: {
        name: 'session_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'timestamp',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ========================================================================
    // Task 3.3: Add guardrail violations table
    // Requirements: 3.3, 3.5, 3.6
    // ========================================================================
    
    this.guardrailTable = new dynamodb.Table(this, 'GuardrailTable', {
      tableName: config.guardrailTableName,
      
      // Same schema as usage records table (Requirement 3.3)
      partitionKey: {
        name: 'user_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'timestamp',
        type: dynamodb.AttributeType.STRING,
      },
      
      // PAY_PER_REQUEST billing (Requirement 3.5)
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      
      // Clean deletion (Requirement 3.6)
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Add session-index GSI (Requirement 3.3)
    this.guardrailTable.addGlobalSecondaryIndex({
      indexName: 'session-index',
      partitionKey: {
        name: 'session_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'timestamp',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ========================================================================
    // Task 3.4: Add prompt templates table
    // Requirements: 3.4, 3.5, 3.6
    // ========================================================================
    
    this.promptTemplatesTable = new dynamodb.Table(this, 'PromptTemplatesTable', {
      tableName: config.promptTemplatesTableName,
      
      // Partition key only: template_id (Requirement 3.4)
      partitionKey: {
        name: 'template_id',
        type: dynamodb.AttributeType.STRING,
      },
      
      // PAY_PER_REQUEST billing (Requirement 3.5)
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      
      // Clean deletion (Requirement 3.6)
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ========================================================================
    // Task 3.4.1: Seed default prompt template
    // ========================================================================
    
    // Custom resource to seed the default "Capabilities" template
    const seedDefaultTemplate = new cr.AwsCustomResource(this, 'SeedDefaultTemplate', {
      onCreate: {
        service: 'DynamoDB',
        action: 'putItem',
        parameters: {
          TableName: this.promptTemplatesTable.tableName,
          Item: {
            template_id: { S: 'default-capabilities' },
            title: { S: 'Capabilities' },
            description: { S: 'How the agent can help' },
            prompt_detail: { S: 'How can you help me?' },
            created_at: { S: new Date().toISOString() },
            updated_at: { S: new Date().toISOString() },
          },
          ConditionExpression: 'attribute_not_exists(template_id)',
        },
        physicalResourceId: cr.PhysicalResourceId.of('default-capabilities'),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['dynamodb:PutItem'],
          resources: [this.promptTemplatesTable.tableArn],
        }),
      ]),
    });

    // Ensure seeding happens after table is created
    seedDefaultTemplate.node.addDependency(this.promptTemplatesTable);

    // ========================================================================
    // Task 3.5: Add stack outputs and exports
    // Requirement: 3.7
    // ========================================================================
    
    // Usage table exports
    new cdk.CfnOutput(this, 'UsageTableName', {
      value: this.usageTable.tableName,
      description: 'Usage records DynamoDB table name',
      exportName: exportNames.usageTableName,
    });

    new cdk.CfnOutput(this, 'UsageTableArn', {
      value: this.usageTable.tableArn,
      description: 'Usage records DynamoDB table ARN',
      exportName: exportNames.usageTableArn,
    });

    // Feedback table exports
    new cdk.CfnOutput(this, 'FeedbackTableName', {
      value: this.feedbackTable.tableName,
      description: 'Feedback DynamoDB table name',
      exportName: exportNames.feedbackTableName,
    });

    new cdk.CfnOutput(this, 'FeedbackTableArn', {
      value: this.feedbackTable.tableArn,
      description: 'Feedback DynamoDB table ARN',
      exportName: exportNames.feedbackTableArn,
    });

    // Guardrail violations table exports
    new cdk.CfnOutput(this, 'GuardrailTableName', {
      value: this.guardrailTable.tableName,
      description: 'Guardrail violations DynamoDB table name',
      exportName: exportNames.guardrailTableName,
    });

    new cdk.CfnOutput(this, 'GuardrailTableArn', {
      value: this.guardrailTable.tableArn,
      description: 'Guardrail violations DynamoDB table ARN',
      exportName: exportNames.guardrailTableArn,
    });

    // Prompt templates table exports
    new cdk.CfnOutput(this, 'PromptTemplatesTableName', {
      value: this.promptTemplatesTable.tableName,
      description: 'Prompt templates DynamoDB table name',
      exportName: exportNames.promptTemplatesTableName,
    });

    new cdk.CfnOutput(this, 'PromptTemplatesTableArn', {
      value: this.promptTemplatesTable.tableArn,
      description: 'Prompt templates DynamoDB table ARN',
      exportName: exportNames.promptTemplatesTableArn,
    });
  }
}
