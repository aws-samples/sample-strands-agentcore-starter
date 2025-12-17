/**
 * Knowledge Base Stack - Bedrock Knowledge Base with S3 Vectors storage.
 * 
 * This stack creates:
 * - IAM role for Bedrock KB operations
 * - S3 bucket for source documents
 * - S3 vector bucket and index for embeddings (via custom resources)
 * - Bedrock Knowledge Base with Titan Embed v2
 * - Data source connecting KB to S3 bucket
 * 
 * Exports:
 * - KnowledgeBaseId
 * - KnowledgeBaseArn
 * - SourceBucketName
 */

import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as cr from 'aws-cdk-lib/custom-resources';
import { Construct } from 'constructs';
import { config, exportNames } from './config';

export class KnowledgeBaseStack extends cdk.Stack {
  /** IAM role for Knowledge Base operations */
  public readonly kbRole: iam.Role;
  
  /** S3 bucket for source documents */
  public readonly sourceBucket: s3.Bucket;
  
  /** Bedrock Knowledge Base */
  public readonly knowledgeBase: bedrock.CfnKnowledgeBase;
  
  /** Data source for the Knowledge Base */
  public readonly dataSource: bedrock.CfnDataSource;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Resource naming
    const vectorBucketName = `${config.appName}-vectors-${this.region}`;
    const vectorIndexName = `${config.appName}-index-${this.region}`;

    // ========================================================================
    // Task 6.1: Create IAM role for Knowledge Base
    // Requirements: 5.1
    // ========================================================================
    
    this.kbRole = new iam.Role(this, 'KnowledgeBaseRole', {
      roleName: `BedrockKBRole-${config.appName}`,
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


    // ========================================================================
    // Task 6.2: Create S3 source bucket for documents
    // Requirements: 5.2
    // ========================================================================
    
    this.sourceBucket = new s3.Bucket(this, 'SourceBucket', {
      bucketName: `${config.appName}-kb-${this.account}-${this.region}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

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

    // ========================================================================
    // Task 6.3: Create S3 vector bucket and index using custom resources
    // Requirements: 5.3
    // ========================================================================
    
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


    // ========================================================================
    // Task 6.4: Create Bedrock Knowledge Base
    // Requirements: 5.4
    // ========================================================================
    
    // Build ARNs for S3 Vectors
    const vectorBucketArn = `arn:aws:s3vectors:${this.region}:${this.account}:bucket/${vectorBucketName}`;
    const indexArn = `arn:aws:s3vectors:${this.region}:${this.account}:bucket/${vectorBucketName}/index/${vectorIndexName}`;

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

    // ========================================================================
    // Task 6.5: Create data source connecting KB to S3
    // Requirements: 5.5
    // ========================================================================
    
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
    // Task 6.6: Add stack outputs and exports
    // Requirements: 5.6
    // ========================================================================
    
    // Export Knowledge Base ID
    new cdk.CfnOutput(this, 'KnowledgeBaseId', {
      value: this.knowledgeBase.attrKnowledgeBaseId,
      description: 'Bedrock Knowledge Base ID',
      exportName: exportNames.knowledgeBaseId,
    });

    // Export Knowledge Base ARN
    new cdk.CfnOutput(this, 'KnowledgeBaseArn', {
      value: this.knowledgeBase.attrKnowledgeBaseArn,
      description: 'Bedrock Knowledge Base ARN',
      exportName: exportNames.knowledgeBaseArn,
    });

    // Export Source Bucket Name
    new cdk.CfnOutput(this, 'SourceBucketName', {
      value: this.sourceBucket.bucketName,
      description: 'S3 bucket for Knowledge Base source documents',
      exportName: exportNames.kbSourceBucketName,
    });

    // Additional outputs for reference
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
  }
}
