/**
 * Foundation Stack - Consolidated stack for authentication, storage, IAM, and secrets.
 * 
 * This stack combines:
 * - Auth: Cognito User Pool and Client
 * - Storage: DynamoDB tables (usage, feedback, guardrail, prompt templates)
 * - IAM: ECS task roles (execution, task, infrastructure)
 * - Secrets: Secrets Manager for application configuration
 * 
 * By consolidating these resources, we reduce cross-stack dependencies and
 * simplify deployment. Internal references are used instead of exports where possible.
 * 
 * Exports (for other stacks):
 * - UserPoolId, UserPoolArn, UserPoolClientId
 * - UsageTableName, UsageTableArn
 * - FeedbackTableName, FeedbackTableArn
 * - GuardrailTableName, GuardrailTableArn
 * - PromptTemplatesTableName, PromptTemplatesTableArn
 * - ExecutionRoleArn, TaskRoleArn, InfrastructureRoleArn
 * - SecretArn
 */

import * as cdk from 'aws-cdk-lib';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as cr from 'aws-cdk-lib/custom-resources';
import { NagSuppressions } from 'cdk-nag';
import { Construct } from 'constructs';
import { config, exportNames } from './config';
import { applyCommonSuppressions, applyEcsSuppressions, applySecretsManagerSuppressions } from './nag-suppressions';

export class FoundationStack extends cdk.Stack {
  // ========================================================================
  // Auth Resources
  // ========================================================================
  
  /** The Cognito User Pool */
  public readonly userPool: cognito.UserPool;
  
  /** The Cognito User Pool Client */
  public readonly userPoolClient: cognito.UserPoolClient;
  
  /** The Admin group */
  public readonly adminGroup: cognito.CfnUserPoolGroup;

  // ========================================================================
  // Storage Resources
  // ========================================================================
  
  /** S3 bucket for server access logs (shared across stacks) */
  public readonly accessLogsBucket: s3.Bucket;
  
  /** Usage records table */
  public readonly usageTable: dynamodb.Table;
  
  /** Feedback table */
  public readonly feedbackTable: dynamodb.Table;
  
  /** Guardrail violations table */
  public readonly guardrailTable: dynamodb.Table;
  
  /** Prompt templates table */
  public readonly promptTemplatesTable: dynamodb.Table;
  
  /** App settings table */
  public readonly appSettingsTable: dynamodb.Table;

  // ========================================================================
  // IAM Resources
  // ========================================================================
  
  /** ECS task execution role */
  public readonly executionRole: iam.Role;
  
  /** ECS task role */
  public readonly taskRole: iam.Role;
  
  /** ECS infrastructure role for Express Mode */
  public readonly infrastructureRole: iam.Role;

  // ========================================================================
  // Secrets Resources
  // ========================================================================
  
  /** The Secrets Manager secret */
  public readonly secret: secretsmanager.Secret;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ========================================================================
    // SECTION 1: COGNITO (Auth)
    // Requirements: 1.2, 2.1
    // ========================================================================
    
    this.userPool = new cognito.UserPool(this, 'UserPool', {
      userPoolName: config.cognitoPoolName,
      
      // Email-based sign-in
      signInAliases: {
        email: true,
        username: false,
      },
      
      // Admin-only user creation
      selfSignUpEnabled: false,
      
      // Auto-verify email
      autoVerify: {
        email: true,
      },
      
      // Password policy
      passwordPolicy: {
        minLength: 8,
        requireUppercase: true,
        requireLowercase: true,
        requireDigits: true,
        requireSymbols: false,
        tempPasswordValidity: cdk.Duration.days(7),
      },
      
      // Standard attributes
      standardAttributes: {
        email: {
          required: true,
          mutable: true,
        },
      },
      
      // Account recovery via email
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      
      // Clean deletion
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    this.userPoolClient = new cognito.UserPoolClient(this, 'UserPoolClient', {
      userPool: this.userPool,
      userPoolClientName: `${config.appName}-client`,
      
      // Authentication flows
      authFlows: {
        userPassword: true,
        userSrp: false,
      },
      
      // Generate client secret for server-side auth
      generateSecret: true,
      
      // Token validity
      accessTokenValidity: cdk.Duration.hours(8),
      idTokenValidity: cdk.Duration.hours(8),
      refreshTokenValidity: cdk.Duration.days(30),
      
      // Prevent user existence errors
      preventUserExistenceErrors: true,
    });

    this.adminGroup = new cognito.CfnUserPoolGroup(this, 'AdminGroup', {
      userPoolId: this.userPool.userPoolId,
      groupName: 'Admin',
      description: 'Administrative access group for managing the chat application',
    });

    // ========================================================================
    // SECTION 2: S3 ACCESS LOGS BUCKET (Shared across stacks)
    // Requirements: Security best practices
    // ========================================================================
    
    this.accessLogsBucket = new s3.Bucket(this, 'AccessLogsBucket', {
      bucketName: `${config.appName}-access-logs-${this.account}-${this.region}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      lifecycleRules: [
        {
          id: 'ExpireOldLogs',
          enabled: true,
          expiration: cdk.Duration.days(90),
        },
      ],
    });

    // Add bucket policy to allow S3 server access logging from other buckets
    this.accessLogsBucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: 'S3ServerAccessLogsPolicy',
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal('logging.s3.amazonaws.com')],
        actions: ['s3:PutObject'],
        resources: [`${this.accessLogsBucket.bucketArn}/*`],
        conditions: {
          ArnLike: {
            'aws:SourceArn': `arn:aws:s3:::${config.appName}-*`,
          },
          StringEquals: {
            'aws:SourceAccount': this.account,
          },
        },
      })
    );

    // ========================================================================
    // SECTION 3: DYNAMODB TABLES (Storage)
    // Requirements: 1.2, 2.1
    // ========================================================================
    
    // Usage records table
    this.usageTable = new dynamodb.Table(this, 'UsageTable', {
      tableName: config.usageTableName,
      partitionKey: {
        name: 'user_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'timestamp',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

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

    // Feedback table
    this.feedbackTable = new dynamodb.Table(this, 'FeedbackTable', {
      tableName: config.feedbackTableName,
      partitionKey: {
        name: 'user_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'timestamp',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

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

    // Guardrail violations table
    this.guardrailTable = new dynamodb.Table(this, 'GuardrailTable', {
      tableName: config.guardrailTableName,
      partitionKey: {
        name: 'user_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'timestamp',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

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

    // Prompt templates table
    this.promptTemplatesTable = new dynamodb.Table(this, 'PromptTemplatesTable', {
      tableName: config.promptTemplatesTableName,
      partitionKey: {
        name: 'template_id',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Seed default prompt template
    const seedDefaultTemplate = new cr.AwsCustomResource(this, 'SeedDefaultTemplate', {
      onCreate: {
        service: 'DynamoDB',
        action: 'putItem',
        parameters: {
          TableName: this.promptTemplatesTable.tableName,
          Item: {
            template_id: { S: 'default-capabilities' },
            title: { S: 'Agent Capabilities' },
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
    seedDefaultTemplate.node.addDependency(this.promptTemplatesTable);

    // App settings table
    this.appSettingsTable = new dynamodb.Table(this, 'AppSettingsTable', {
      tableName: config.appSettingsTableName,
      partitionKey: {
        name: 'setting_key',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Seed default app settings
    const seedDefaultSettings = new cr.AwsCustomResource(this, 'SeedDefaultSettings', {
      onCreate: {
        service: 'DynamoDB',
        action: 'batchWriteItem',
        parameters: {
          RequestItems: {
            [this.appSettingsTable.tableName]: [
              {
                PutRequest: {
                  Item: {
                    setting_key: { S: 'app_title' },
                    setting_value: { S: 'Chat Agent' },
                    setting_type: { S: 'text' },
                    description: { S: 'Application title displayed in header' },
                    updated_at: { S: new Date().toISOString() },
                  },
                },
              },
              {
                PutRequest: {
                  Item: {
                    setting_key: { S: 'app_subtitle' },
                    setting_value: { S: 'Bedrock AgentCore + Strands Agents SDK' },
                    setting_type: { S: 'text' },
                    description: { S: 'Application subtitle displayed in header' },
                    updated_at: { S: new Date().toISOString() },
                  },
                },
              },
              {
                PutRequest: {
                  Item: {
                    setting_key: { S: 'logo_url' },
                    setting_value: { S: '/static/favicon.svg' },
                    setting_type: { S: 'image' },
                    description: { S: 'Application logo displayed in header' },
                    updated_at: { S: new Date().toISOString() },
                  },
                },
              },
              {
                PutRequest: {
                  Item: {
                    setting_key: { S: 'chat_logo_url' },
                    setting_value: { S: '/static/chat-placeholder.svg' },
                    setting_type: { S: 'image' },
                    description: { S: 'Chat placeholder logo displayed in empty chat screen' },
                    updated_at: { S: new Date().toISOString() },
                  },
                },
              },
            ],
          },
        },
        physicalResourceId: cr.PhysicalResourceId.of('default-app-settings'),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['dynamodb:BatchWriteItem'],
          resources: [this.appSettingsTable.tableArn],
        }),
      ]),
    });
    seedDefaultSettings.node.addDependency(this.appSettingsTable);

    // ========================================================================
    // SECTION 4: IAM ROLES
    // Requirements: 1.2, 2.1
    // ========================================================================
    
    // ECS task execution role
    this.executionRole = new iam.Role(this, 'TaskExecutionRole', {
      roleName: `${config.appName}-ecs-execution-role-${this.region}`,
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      description: 'ECS task execution role for pulling images and writing logs',
    });

    this.executionRole.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy')
    );

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

    // ECS task role
    this.taskRole = new iam.Role(this, 'TaskRole', {
      roleName: `${config.appName}-ecs-task-role-${this.region}`,
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      description: 'ECS task role with permissions for AgentCore, Cognito, DynamoDB, Bedrock',
    });

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

    // AgentCore Memory permissions
    this.taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'AgentCoreMemoryAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock-agentcore:GetMemory',
          'bedrock-agentcore:ListMemories',
          'bedrock-agentcore:ListEvents',
          'bedrock-agentcore:GetEvent',
          'bedrock-agentcore:ListMemoryRecords',
          'bedrock-agentcore:GetMemoryRecord',
          'bedrock-agentcore:SearchMemoryRecords',
        ],
        resources: [
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:memory/*`,
        ],
      })
    );

    // Cognito permissions - using internal reference
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
        resources: [this.userPool.userPoolArn],
      })
    );

    // DynamoDB permissions - using internal references
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
          this.usageTable.tableArn,
          `${this.usageTable.tableArn}/index/*`,
          this.feedbackTable.tableArn,
          `${this.feedbackTable.tableArn}/index/*`,
          this.guardrailTable.tableArn,
          `${this.guardrailTable.tableArn}/index/*`,
          this.promptTemplatesTable.tableArn,
          `${this.promptTemplatesTable.tableArn}/index/*`,
          this.appSettingsTable.tableArn,
          `${this.appSettingsTable.tableArn}/index/*`,
        ],
      })
    );

    // Bedrock model invocation
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

    // CloudWatch Logs permissions
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

    // ECS infrastructure role for Express Mode
    this.infrastructureRole = new iam.Role(this, 'InfrastructureRole', {
      roleName: `${config.appName}-ecs-infrastructure-role-${this.region}`,
      assumedBy: new iam.ServicePrincipal('ecs.amazonaws.com'),
      description: 'ECS infrastructure role for Express Mode services',
    });

    this.infrastructureRole.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSInfrastructureRoleforExpressGatewayServices')
    );

    // ========================================================================
    // SECTION 5: SECRETS MANAGER
    // Requirements: 1.2, 2.1
    // Note: Some values will be added by other stacks via custom resource updates
    // ========================================================================
    
    // Custom resource to retrieve Cognito User Pool Client secret
    const getCognitoClientSecret = new cr.AwsCustomResource(this, 'GetCognitoClientSecret', {
      onCreate: {
        service: 'CognitoIdentityServiceProvider',
        action: 'describeUserPoolClient',
        parameters: {
          UserPoolId: this.userPool.userPoolId,
          ClientId: this.userPoolClient.userPoolClientId,
        },
        physicalResourceId: cr.PhysicalResourceId.of('CognitoClientSecret'),
      },
      onUpdate: {
        service: 'CognitoIdentityServiceProvider',
        action: 'describeUserPoolClient',
        parameters: {
          UserPoolId: this.userPool.userPoolId,
          ClientId: this.userPoolClient.userPoolClientId,
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

    const cognitoClientSecret = getCognitoClientSecret.getResponseField('UserPoolClient.ClientSecret');

    // Create the Secrets Manager secret with Foundation stack values
    // Values from Bedrock and Agent stacks will be added via updates
    this.secret = new secretsmanager.Secret(this, 'AppConfigSecret', {
      secretName: config.secretName,
      description: 'Application configuration for AgentCore Chat Application',
      
      secretObjectValue: {
        // Cognito credentials (internal references)
        cognito_user_pool_id: cdk.SecretValue.unsafePlainText(this.userPool.userPoolId),
        cognito_client_id: cdk.SecretValue.unsafePlainText(this.userPoolClient.userPoolClientId),
        cognito_client_secret: cdk.SecretValue.unsafePlainText(cognitoClientSecret),
        
        // AWS configuration
        aws_region: cdk.SecretValue.unsafePlainText(this.region),
        app_url: cdk.SecretValue.unsafePlainText(''),  // Updated after ChatApp deployment
        
        // DynamoDB table names (internal references)
        usage_table_name: cdk.SecretValue.unsafePlainText(this.usageTable.tableName),
        feedback_table_name: cdk.SecretValue.unsafePlainText(this.feedbackTable.tableName),
        guardrail_table_name: cdk.SecretValue.unsafePlainText(this.guardrailTable.tableName),
        prompt_templates_table_name: cdk.SecretValue.unsafePlainText(this.promptTemplatesTable.tableName),
        app_settings_table_name: cdk.SecretValue.unsafePlainText(this.appSettingsTable.tableName),
        
        // Placeholders for values from other stacks (will be updated)
        agentcore_runtime_arn: cdk.SecretValue.unsafePlainText(''),
        memory_id: cdk.SecretValue.unsafePlainText(''),
        guardrail_id: cdk.SecretValue.unsafePlainText(''),
        guardrail_version: cdk.SecretValue.unsafePlainText(''),
        kb_id: cdk.SecretValue.unsafePlainText(''),
      },
      
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    this.secret.node.addDependency(getCognitoClientSecret);

    // Add resource policy for execution role access
    this.secret.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: 'AllowECSExecutionRoleAccess',
        effect: iam.Effect.ALLOW,
        principals: [new iam.ArnPrincipal(this.executionRole.roleArn)],
        actions: [
          'secretsmanager:GetSecretValue',
          'secretsmanager:DescribeSecret',
        ],
        resources: ['*'],
      })
    );


    // ========================================================================
    // SECTION 6: EXPORTS
    // Requirements: 2.3
    // 
    // Only exports needed by other stacks are defined here.
    // Auth and Storage values are internal to this stack and passed via Secrets.
    // ========================================================================
    
    // --- Cross-stack exports (used by ChatApp Stack) ---
    
    new cdk.CfnOutput(this, 'ExecutionRoleArn', {
      value: this.executionRole.roleArn,
      description: 'ECS task execution role ARN',
      exportName: exportNames.executionRoleArn,
    });

    new cdk.CfnOutput(this, 'TaskRoleArn', {
      value: this.taskRole.roleArn,
      description: 'ECS task role ARN',
      exportName: exportNames.taskRoleArn,
    });

    new cdk.CfnOutput(this, 'InfrastructureRoleArn', {
      value: this.infrastructureRole.roleArn,
      description: 'ECS infrastructure role ARN for Express Mode',
      exportName: exportNames.infrastructureRoleArn,
    });

    new cdk.CfnOutput(this, 'SecretArn', {
      value: this.secret.secretArn,
      description: 'Secrets Manager secret ARN',
      exportName: exportNames.secretArn,
    });

    // --- Internal outputs (not exported, for reference only) ---
    
    new cdk.CfnOutput(this, 'UserPoolId', {
      value: this.userPool.userPoolId,
      description: 'Cognito User Pool ID',
    });

    new cdk.CfnOutput(this, 'UserPoolClientId', {
      value: this.userPoolClient.userPoolClientId,
      description: 'Cognito User Pool Client ID',
    });

    new cdk.CfnOutput(this, 'UsageTableName', {
      value: this.usageTable.tableName,
      description: 'Usage records DynamoDB table name',
    });

    new cdk.CfnOutput(this, 'FeedbackTableName', {
      value: this.feedbackTable.tableName,
      description: 'Feedback DynamoDB table name',
    });

    new cdk.CfnOutput(this, 'GuardrailTableName', {
      value: this.guardrailTable.tableName,
      description: 'Guardrail violations DynamoDB table name',
    });

    new cdk.CfnOutput(this, 'PromptTemplatesTableName', {
      value: this.promptTemplatesTable.tableName,
      description: 'Prompt templates DynamoDB table name',
    });

    new cdk.CfnOutput(this, 'AppSettingsTableName', {
      value: this.appSettingsTable.tableName,
      description: 'App settings DynamoDB table name',
    });

    new cdk.CfnOutput(this, 'SecretName', {
      value: this.secret.secretName,
      description: 'Secrets Manager secret name',
    });

    new cdk.CfnOutput(this, 'AccessLogsBucketName', {
      value: this.accessLogsBucket.bucketName,
      description: 'S3 bucket for server access logs',
      exportName: `${config.appName}-AccessLogsBucketName`,
    });

    new cdk.CfnOutput(this, 'AccessLogsBucketArn', {
      value: this.accessLogsBucket.bucketArn,
      description: 'S3 bucket ARN for server access logs',
      exportName: `${config.appName}-AccessLogsBucketArn`,
    });

    // ========================================================================
    // CDK-NAG SUPPRESSIONS
    // ========================================================================
    
    applyCommonSuppressions(this);
    applyEcsSuppressions(this);
    applySecretsManagerSuppressions(this);

    // Suppress Cognito findings - acceptable for starter kit
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Foundation/UserPool/Resource`,
      [
        {
          id: 'AwsSolutions-COG1',
          reason: 'Password policy requires 8+ chars, uppercase, lowercase, and digits. Special chars not required for starter kit usability.',
        },
        {
          id: 'AwsSolutions-COG2',
          reason: 'MFA not required for starter kit / PoC. Can be enabled for production deployments.',
        },
        {
          id: 'AwsSolutions-COG3',
          reason: 'Advanced security mode not enabled for starter kit to reduce costs. Can be enabled for production.',
        },
      ]
    );

    // Suppress access logs bucket self-logging (cannot log to itself)
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Foundation/AccessLogsBucket/Resource`,
      [
        {
          id: 'AwsSolutions-S1',
          reason: 'Access logs bucket cannot log to itself. This is the central logging bucket for all other S3 buckets.',
        },
      ]
    );

    // Suppress DynamoDB PITR warnings - acceptable for starter kit
    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-DDB3',
        reason: 'Point-in-time recovery not enabled for starter kit to reduce costs. Can be enabled for production deployments.',
      },
    ]);

    // Suppress execution role secret access wildcard
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Foundation/TaskExecutionRole/DefaultPolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'Secret ARN includes random suffix generated by Secrets Manager. Scoped to specific secret name prefix.',
          appliesTo: [`Resource::arn:aws:secretsmanager:${this.region}:${this.account}:secret:${config.secretName}*`],
        },
      ]
    );

    // Suppress wildcard for Cognito user pool (custom resource needs to describe any pool)
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Foundation/GetCognitoClientSecret/CustomResourcePolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'Custom resource needs to describe user pool client to retrieve client secret. Pool ID is not known at synthesis time.',
          appliesTo: [`Resource::arn:aws:cognito-idp:${this.region}:${this.account}:userpool/*`],
        },
      ]
    );

    // Suppress wildcards for task role - these are scoped appropriately
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Foundation/TaskRole/DefaultPolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'AgentCore Runtime invocation requires wildcard as runtime ARN is not known at synthesis time.',
          appliesTo: ['Resource::*'],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'Bedrock foundation models require wildcard pattern. Scoped to InvokeModel actions only.',
          appliesTo: [`Resource::arn:aws:bedrock:${this.region}::foundation-model/*`],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'AgentCore Memory ID is dynamic. Scoped to memory resources only.',
          appliesTo: [`Resource::arn:aws:bedrock-agentcore:${this.region}:${this.account}:memory/*`],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'CloudWatch log group name includes dynamic service name. Scoped to app-specific log groups.',
          appliesTo: [`Resource::arn:aws:logs:${this.region}:${this.account}:log-group:/ecs/${config.appName}*`],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'DynamoDB GSI access requires index/* pattern. Scoped to specific tables.',
          appliesTo: [
            'Resource::<UsageTable28300137.Arn>/index/*',
            'Resource::<FeedbackTableF528636C.Arn>/index/*',
            'Resource::<GuardrailTableE43D96F7.Arn>/index/*',
            'Resource::<PromptTemplatesTableAA30D6E4.Arn>/index/*',
            'Resource::<AppSettingsTable41A0871E.Arn>/index/*',
          ],
        },
      ]
    );
  }

  /**
   * Add Bedrock Guardrail permissions to the task role.
   * Called by Bedrock stack after guardrail is created.
   */
  public addGuardrailPermissions(guardrailArn: string): void {
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
  }

  /**
   * Add Bedrock Knowledge Base permissions to the task role.
   * Called by Bedrock stack after knowledge base is created.
   */
  public addKnowledgeBasePermissions(knowledgeBaseArn: string): void {
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
  }
}
