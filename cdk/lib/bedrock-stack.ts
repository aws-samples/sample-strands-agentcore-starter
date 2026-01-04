/**
 * Bedrock Stack - Consolidated stack for all Bedrock-related resources.
 * 
 * This stack combines:
 * - Guardrail (from guardrail-stack.ts) - Content filtering
 * - Knowledge Base (from knowledgebase-stack.ts) - Semantic search with S3 Vectors
 * - Memory (from memory-stack.ts) - AgentCore Memory for conversation persistence
 * 
 * Exports:
 * - GuardrailId, GuardrailVersion, GuardrailArn
 * - KnowledgeBaseId, KnowledgeBaseArn, SourceBucketName
 * - MemoryId, MemoryArn
 */

import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as bedrockagentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as cr from 'aws-cdk-lib/custom-resources';
import { NagSuppressions } from 'cdk-nag';
import { Construct } from 'constructs';
import { config, exportNames } from './config';
import { applyCommonSuppressions } from './nag-suppressions';

export class BedrockStack extends cdk.Stack {
  // Guardrail resources
  /** The Bedrock Guardrail */
  public readonly guardrail: bedrock.CfnGuardrail;
  /** The published Guardrail version */
  public readonly guardrailVersion: bedrock.CfnGuardrailVersion;

  // Knowledge Base resources
  /** IAM role for Knowledge Base operations */
  public readonly kbRole: iam.Role;
  /** S3 bucket for source documents */
  public readonly sourceBucket: s3.Bucket;
  /** Bedrock Knowledge Base */
  public readonly knowledgeBase: bedrock.CfnKnowledgeBase;
  /** Data source for the Knowledge Base */
  public readonly dataSource: bedrock.CfnDataSource;

  // Memory resources
  /** The AgentCore Memory resource */
  public readonly memory: bedrockagentcore.CfnMemory;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ========================================================================
    // GUARDRAIL SECTION
    // Requirements: 1.3, 2.1
    // ========================================================================

    
    this.guardrail = new bedrock.CfnGuardrail(this, 'Guardrail', {
      name: config.guardrailName,
      
      // Blocked messaging
      blockedInputMessaging: 'Your message could not be processed due to content policy restrictions.',
      blockedOutputsMessaging: 'The response could not be provided due to content policy restrictions.',
      
      // Content policy with MEDIUM strength filters
      contentPolicyConfig: {
        filtersConfig: [
          {
            type: 'HATE',
            inputStrength: 'MEDIUM',
            outputStrength: 'MEDIUM',
          },
          {
            type: 'VIOLENCE',
            inputStrength: 'MEDIUM',
            outputStrength: 'MEDIUM',
          },
          {
            type: 'SEXUAL',
            inputStrength: 'MEDIUM',
            outputStrength: 'MEDIUM',
          },
          {
            type: 'INSULTS',
            inputStrength: 'MEDIUM',
            outputStrength: 'MEDIUM',
          },
          {
            type: 'MISCONDUCT',
            inputStrength: 'MEDIUM',
            outputStrength: 'MEDIUM',
          },
        ],
      },
      
      description: 'Content filtering guardrail for AgentCore Chat Application',
    });

    // Create guardrail version
    this.guardrailVersion = new bedrock.CfnGuardrailVersion(this, 'GuardrailVersion', {
      guardrailIdentifier: this.guardrail.attrGuardrailId,
      description: 'Version 1 - Initial production release',
    });
    
    // Ensure version is created after guardrail
    this.guardrailVersion.addDependency(this.guardrail);

    // ========================================================================
    // KNOWLEDGE BASE SECTION
    // Requirements: 1.3, 2.1
    // ========================================================================

    // Resource naming
    const vectorBucketName = `${config.appName}-vectors-${this.region}`;
    const vectorIndexName = `${config.appName}-index-${this.region}`;

    // Create IAM role for Knowledge Base
    this.kbRole = new iam.Role(this, 'KnowledgeBaseRole', {
      roleName: `BedrockKBRole-${config.appName}-${this.region}`,
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com', {
        conditions: {
          StringEquals: {
            'aws:SourceAccount': this.account,
          },
          ArnLike: {
            'aws:SourceArn': `arn:aws:bedrock:${this.region}:${this.account}:knowledge-base/*`,
          },
        },
      }),
      description: 'IAM role for Bedrock Knowledge Base operations',
    });

    // Bedrock model invocation permission for Titan Embed v2
    this.kbRole.addToPolicy(new iam.PolicyStatement({
      sid: 'BedrockInvokeModel',
      effect: iam.Effect.ALLOW,
      actions: ['bedrock:InvokeModel'],
      resources: [
        `arn:aws:bedrock:${this.region}::foundation-model/amazon.titan-embed-text-v2:0`,
      ],
    }));

    // Create S3 source bucket for documents
    // Import access logs bucket from Foundation stack
    const accessLogsBucketName = cdk.Fn.importValue(`${config.appName}-AccessLogsBucketName`);
    const accessLogsBucket = s3.Bucket.fromBucketName(this, 'ImportedAccessLogsBucket', accessLogsBucketName);

    this.sourceBucket = new s3.Bucket(this, 'SourceBucket', {
      bucketName: `${config.appName}-kb-${this.account}-${this.region}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      serverAccessLogsBucket: accessLogsBucket,
      serverAccessLogsPrefix: 'kb-source-bucket/',
    });

    // Acknowledge that logging permissions are handled in Foundation stack
    cdk.Annotations.of(this.sourceBucket).acknowledgeWarning('@aws-cdk/aws-s3:accessLogsPolicyNotAdded', 'Logging permissions added to access logs bucket in Foundation stack');

    // Add S3 source bucket access to KB role
    this.kbRole.addToPolicy(new iam.PolicyStatement({
      sid: 'S3SourceBucketAccess',
      effect: iam.Effect.ALLOW,
      actions: [
        's3:GetObject',
        's3:ListBucket',
      ],
      resources: [
        this.sourceBucket.bucketArn,
        `${this.sourceBucket.bucketArn}/*`,
      ],
    }));

    // S3 Vectors permissions for KB role
    this.kbRole.addToPolicy(new iam.PolicyStatement({
      sid: 'S3VectorsAccess',
      effect: iam.Effect.ALLOW,
      actions: [
        's3vectors:CreateIndex',
        's3vectors:DeleteIndex',
        's3vectors:GetIndex',
        's3vectors:ListIndexes',
        's3vectors:PutVectors',
        's3vectors:GetVectors',
        's3vectors:DeleteVectors',
        's3vectors:QueryVectors',
      ],
      resources: [
        `arn:aws:s3vectors:${this.region}:${this.account}:bucket/${vectorBucketName}`,
        `arn:aws:s3vectors:${this.region}:${this.account}:bucket/${vectorBucketName}/index/*`,
      ],
    }));

    // Custom resource to create S3 vector bucket
    const createVectorBucket = new cr.AwsCustomResource(this, 'CreateVectorBucket', {
      onCreate: {
        service: 's3vectors',
        action: 'CreateVectorBucket',
        parameters: {
          vectorBucketName: vectorBucketName,
        },
        physicalResourceId: cr.PhysicalResourceId.of(vectorBucketName),
      },
      onDelete: {
        service: 's3vectors',
        action: 'DeleteVectorBucket',
        parameters: {
          vectorBucketName: vectorBucketName,
        },
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: [
            's3vectors:CreateVectorBucket',
            's3vectors:DeleteVectorBucket',
            's3vectors:GetVectorBucket',
          ],
          resources: ['*'],
        }),
      ]),
    });

    // Custom resource to create vector index
    const createVectorIndex = new cr.AwsCustomResource(this, 'CreateVectorIndex', {
      onCreate: {
        service: 's3vectors',
        action: 'CreateIndex',
        parameters: {
          vectorBucketName: vectorBucketName,
          indexName: vectorIndexName,
          dataType: 'float32',
          dimension: 1024, // Titan Embed v2 dimensions
          distanceMetric: 'cosine',
          metadataConfiguration: {
            nonFilterableMetadataKeys: ['AMAZON_BEDROCK_TEXT', 'AMAZON_BEDROCK_METADATA'],
          },
        },
        physicalResourceId: cr.PhysicalResourceId.of(`${vectorBucketName}/${vectorIndexName}`),
      },
      onDelete: {
        service: 's3vectors',
        action: 'DeleteIndex',
        parameters: {
          vectorBucketName: vectorBucketName,
          indexName: vectorIndexName,
        },
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: [
            's3vectors:CreateIndex',
            's3vectors:DeleteIndex',
            's3vectors:GetIndex',
          ],
          resources: [
            `arn:aws:s3vectors:${this.region}:${this.account}:bucket/${vectorBucketName}`,
            `arn:aws:s3vectors:${this.region}:${this.account}:bucket/${vectorBucketName}/index/*`,
          ],
        }),
      ]),
    });

    // Ensure index is created after bucket
    createVectorIndex.node.addDependency(createVectorBucket);

    // Build ARNs for S3 Vectors
    const vectorBucketArn = `arn:aws:s3vectors:${this.region}:${this.account}:bucket/${vectorBucketName}`;
    const indexArn = `arn:aws:s3vectors:${this.region}:${this.account}:bucket/${vectorBucketName}/index/${vectorIndexName}`;

    // Create Bedrock Knowledge Base
    this.knowledgeBase = new bedrock.CfnKnowledgeBase(this, 'KnowledgeBase', {
      name: config.kbName,
      description: `Knowledge Base for ${config.appName} agent`,
      roleArn: this.kbRole.roleArn,
      
      // Vector knowledge base configuration with Titan Embed v2
      knowledgeBaseConfiguration: {
        type: 'VECTOR',
        vectorKnowledgeBaseConfiguration: {
          embeddingModelArn: `arn:aws:bedrock:${this.region}::foundation-model/amazon.titan-embed-text-v2:0`,
        },
      },
      
      // S3 Vectors storage configuration
      storageConfiguration: {
        type: 'S3_VECTORS',
        s3VectorsConfiguration: {
          vectorBucketArn: vectorBucketArn,
          indexArn: indexArn,
        },
      },
    });

    // Ensure KB is created after vector index
    this.knowledgeBase.node.addDependency(createVectorIndex);

    // Create data source connecting KB to S3
    this.dataSource = new bedrock.CfnDataSource(this, 'DataSource', {
      knowledgeBaseId: this.knowledgeBase.attrKnowledgeBaseId,
      name: `${config.appName}-kb-datasource`,
      description: `S3 data source for ${config.appName} Knowledge Base`,
      
      // S3 data source configuration
      dataSourceConfiguration: {
        type: 'S3',
        s3Configuration: {
          bucketArn: this.sourceBucket.bucketArn,
          inclusionPrefixes: ['documents/'],
        },
      },
      
      // Retain data when data source is deleted
      dataDeletionPolicy: 'RETAIN',
    });

    // Ensure data source is created after KB
    this.dataSource.addDependency(this.knowledgeBase);


    // ========================================================================
    // MEMORY SECTION
    // Requirements: 1.3, 2.1
    // ========================================================================
    
    // Memory name must match pattern: ^[a-zA-Z][a-zA-Z0-9_]{0,47}$
    // Replace hyphens with underscores
    const memoryName = `${config.appName.replace(/-/g, '_')}_memory`;
    
    this.memory = new bedrockagentcore.CfnMemory(this, 'AgentMemory', {
      name: memoryName,
      description: `AgentCore Memory for ${config.appName} conversation persistence`,
      
      // Event retention: 30 days for short-term memory
      eventExpiryDuration: 30,
      
      // Memory strategies for long-term memory extraction
      memoryStrategies: [
        {
          // Summary strategy - creates session summaries
          summaryMemoryStrategy: {
            name: 'SessionSummarizer',
            namespaces: ['/summaries/{actorId}/{sessionId}'],
          },
        },
        {
          // User preference strategy - extracts user preferences
          userPreferenceMemoryStrategy: {
            name: 'PreferenceLearner',
            namespaces: ['/users/{actorId}/preferences'],
          },
        },
        {
          // Semantic fact strategy - extracts facts from conversations
          semanticMemoryStrategy: {
            name: 'FactExtractor',
            namespaces: ['/users/{actorId}/facts'],
          },
        },
      ],
      
      // Tags
      tags: {
        Application: config.appName,
        ManagedBy: 'CDK',
      },
    });

    // ========================================================================
    // UPDATE SECRETS MANAGER WITH BEDROCK VALUES
    // Requirements: 2.1, 2.3
    // ========================================================================
    
    // Import secret ARN from Foundation stack
    const secretArn = cdk.Fn.importValue(exportNames.secretArn);
    
    // Lambda function to merge values into existing secret
    const updateSecretFunction = new lambda.Function(this, 'UpdateSecretFunction', {
      functionName: `${config.appName}-update-secret-bedrock`,
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

    const updateSecretWithBedrockValues = new cdk.CustomResource(this, 'UpdateSecretWithBedrockValues', {
      serviceToken: updateSecretProvider.serviceToken,
      properties: {
        SecretId: secretArn,
        NewValues: JSON.stringify({
          guardrail_id: this.guardrail.attrGuardrailId,
          guardrail_version: this.guardrailVersion.attrVersion,
          kb_id: this.knowledgeBase.attrKnowledgeBaseId,
          memory_id: this.memory.attrMemoryId,
        }),
        Timestamp: Date.now().toString(),
      },
    });

    // Ensure secret update happens after all resources are created
    updateSecretWithBedrockValues.node.addDependency(this.guardrailVersion);
    updateSecretWithBedrockValues.node.addDependency(this.knowledgeBase);
    updateSecretWithBedrockValues.node.addDependency(this.memory);

    // ========================================================================
    // STACK OUTPUTS AND EXPORTS
    // Requirements: 2.3
    // 
    // Only exports needed by Agent Stack are defined here.
    // ========================================================================

    // --- Cross-stack exports (used by Agent Stack) ---
    
    new cdk.CfnOutput(this, 'GuardrailId', {
      value: this.guardrail.attrGuardrailId,
      description: 'Bedrock Guardrail ID',
      exportName: exportNames.guardrailId,
    });

    new cdk.CfnOutput(this, 'GuardrailVersionOutput', {
      value: this.guardrailVersion.attrVersion,
      description: 'Bedrock Guardrail Version',
      exportName: exportNames.guardrailVersion,
    });

    new cdk.CfnOutput(this, 'KnowledgeBaseId', {
      value: this.knowledgeBase.attrKnowledgeBaseId,
      description: 'Bedrock Knowledge Base ID',
      exportName: exportNames.knowledgeBaseId,
    });

    new cdk.CfnOutput(this, 'MemoryId', {
      value: this.memory.attrMemoryId,
      description: 'AgentCore Memory ID',
      exportName: exportNames.memoryId,
    });

    new cdk.CfnOutput(this, 'MemoryArn', {
      value: this.memory.attrMemoryArn,
      description: 'AgentCore Memory ARN',
      exportName: exportNames.memoryArn,
    });

    // --- Internal outputs (not exported, for reference only) ---
    
    new cdk.CfnOutput(this, 'GuardrailArn', {
      value: this.guardrail.attrGuardrailArn,
      description: 'Bedrock Guardrail ARN',
    });

    new cdk.CfnOutput(this, 'KnowledgeBaseArn', {
      value: this.knowledgeBase.attrKnowledgeBaseArn,
      description: 'Bedrock Knowledge Base ARN',
    });

    new cdk.CfnOutput(this, 'SourceBucketName', {
      value: this.sourceBucket.bucketName,
      description: 'S3 bucket for Knowledge Base source documents',
    });

    new cdk.CfnOutput(this, 'VectorBucketName', {
      value: vectorBucketName,
      description: 'S3 vector bucket name',
    });

    new cdk.CfnOutput(this, 'VectorIndexName', {
      value: vectorIndexName,
      description: 'S3 vector index name',
    });

    new cdk.CfnOutput(this, 'DataSourceId', {
      value: this.dataSource.attrDataSourceId,
      description: 'Knowledge Base data source ID',
    });

    // ========================================================================
    // CDK-NAG SUPPRESSIONS
    // ========================================================================
    
    applyCommonSuppressions(this);

    // Suppress S3 vectors custom resource wildcards
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Bedrock/CreateVectorBucket/CustomResourcePolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'S3 Vectors CreateVectorBucket requires wildcard as bucket name is dynamic. This is a one-time setup operation.',
          appliesTo: ['Resource::*'],
        },
      ]
    );

    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Bedrock/CreateVectorIndex/CustomResourcePolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'S3 Vectors index operations require wildcard for index name. Scoped to specific vector bucket.',
          appliesTo: [`Resource::arn:aws:s3vectors:${this.region}:${this.account}:bucket/${vectorBucketName}/index/*`],
        },
      ]
    );

    // Suppress Knowledge Base role wildcards
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Bedrock/KnowledgeBaseRole/DefaultPolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'Knowledge Base needs access to all objects in source bucket for document ingestion.',
          appliesTo: ['Resource::<SourceBucketDDD2130A.Arn>/*'],
        },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'S3 Vectors index operations require wildcard for vector operations. Scoped to specific vector bucket.',
          appliesTo: [`Resource::arn:aws:s3vectors:${this.region}:${this.account}:bucket/${vectorBucketName}/index/*`],
        },
      ]
    );

    // Suppress update secret function wildcards
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Bedrock/UpdateSecretFunction/ServiceRole/DefaultPolicy/Resource`,
      [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'Secret ARN includes random suffix. Scoped to specific secret name prefix.',
          appliesTo: [`Resource::arn:aws:secretsmanager:${this.region}:${this.account}:secret:${config.secretName}*`],
        },
      ]
    );

    // Suppress provider framework wildcards (CDK-managed)
    NagSuppressions.addResourceSuppressionsByPath(
      this,
      `/${config.appName}-Bedrock/UpdateSecretProvider/framework-onEvent/ServiceRole/DefaultPolicy/Resource`,
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
