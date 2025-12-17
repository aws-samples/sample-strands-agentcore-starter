/**
 * Agent Runtime Stack - AgentCore CfnRuntime deployment.
 * 
 * This stack creates:
 * - S3 deployment of agent source files for CodeBuild
 * - Custom resource to trigger CodeBuild
 * - Lambda function to wait for CodeBuild completion
 * - CfnRuntime resource for AgentCore
 * 
 * Exports:
 * - AgentRuntimeArn
 * - AgentRuntimeEndpoint
 */

import * as cdk from 'aws-cdk-lib';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as bedrockagentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import { config, exportNames } from './config';
import * as path from 'path';

export class AgentRuntimeStack extends cdk.Stack {
  /** The AgentCore CfnRuntime */
  public readonly agentRuntime: bedrockagentcore.CfnRuntime;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Import values from dependent stacks
    const agentRepositoryUri = cdk.Fn.importValue(exportNames.agentRepositoryUri);
    const buildSourceBucketName = cdk.Fn.importValue(exportNames.buildSourceBucketName);
    const buildProjectName = cdk.Fn.importValue(exportNames.buildProjectName);
    const agentRuntimeRoleArn = cdk.Fn.importValue(exportNames.agentRuntimeRoleArn);
    const guardrailId = cdk.Fn.importValue(exportNames.guardrailId);
    const guardrailVersion = cdk.Fn.importValue(exportNames.guardrailVersion);
    const knowledgeBaseId = cdk.Fn.importValue(exportNames.knowledgeBaseId);
    const memoryId = cdk.Fn.importValue(exportNames.memoryId);

    // Reference the source bucket from AgentInfra stack
    const sourceBucket = s3.Bucket.fromBucketName(
      this,
      'SourceBucket',
      buildSourceBucketName
    );


    // ========================================================================
    // Task 10.1: Upload agent source files to S3 for CodeBuild
    // Requirements: 15.1
    // ========================================================================
    
    // Deploy agent source files to S3 bucket
    // Excludes: venv, __pycache__, .git, node_modules, .env, .bedrock_agentcore
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
      destinationBucket: sourceBucket,
      destinationKeyPrefix: 'agent-source',
      prune: true,
      retainOnDelete: false,
      memoryLimit: 512,
    });

    // ========================================================================
    // Task 10.2: Create CodeBuild trigger custom resource
    // Requirements: 15.2
    // ========================================================================
    
    // Custom resource to trigger CodeBuild after source upload
    // Note: S3 source location format is "bucket-name/path/" with trailing slash for directories
    const triggerBuild = new cr.AwsCustomResource(this, 'TriggerCodeBuild', {
      onCreate: {
        service: 'CodeBuild',
        action: 'startBuild',
        parameters: {
          projectName: buildProjectName,
          sourceTypeOverride: 'S3',
          sourceLocationOverride: `${buildSourceBucketName}/agent-source/`,
        },
        physicalResourceId: cr.PhysicalResourceId.fromResponse('build.id'),
      },
      onUpdate: {
        service: 'CodeBuild',
        action: 'startBuild',
        parameters: {
          projectName: buildProjectName,
          sourceTypeOverride: 'S3',
          sourceLocationOverride: `${buildSourceBucketName}/agent-source/`,
        },
        physicalResourceId: cr.PhysicalResourceId.fromResponse('build.id'),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['codebuild:StartBuild'],
          resources: [`arn:aws:codebuild:${this.region}:${this.account}:project/${config.agentBuildProjectName}`],
        }),
      ]),
    });

    // Ensure build is triggered after source upload
    triggerBuild.node.addDependency(agentSourceDeployment);


    // ========================================================================
    // Task 10.3: Create build waiter Lambda function
    // Requirements: 15.3
    // ========================================================================
    
    // Lambda function to wait for CodeBuild completion
    const buildWaiterFunction = new lambda.Function(this, 'BuildWaiterFunction', {
      functionName: `${config.appName}-build-waiter`,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'index.handler',
      timeout: cdk.Duration.minutes(14), // Max 15 min, use 14 for safety
      memorySize: 128,
      code: lambda.Code.fromInline(`
import boto3
import time
import json
import cfnresponse

def handler(event, context):
    """
    Wait for CodeBuild to complete.
    Polls every 30 seconds, times out after 14 minutes.
    """
    print(f"Event: {json.dumps(event)}")
    
    # Handle Delete - just succeed
    if event['RequestType'] == 'Delete':
        cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
        return
    
    try:
        build_id = event['ResourceProperties']['BuildId']
        codebuild = boto3.client('codebuild')
        
        # Poll for build completion (max ~14 minutes)
        max_attempts = 28  # 28 * 30 seconds = 14 minutes
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
            
            # Still in progress, wait 30 seconds
            time.sleep(30)
        
        # Timeout
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

    // Grant Lambda permission to check CodeBuild status
    buildWaiterFunction.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['codebuild:BatchGetBuilds'],
        resources: [`arn:aws:codebuild:${this.region}:${this.account}:project/${config.agentBuildProjectName}`],
      })
    );

    // Create custom resource provider for build waiter
    const buildWaiterProvider = new cr.Provider(this, 'BuildWaiterProvider', {
      onEventHandler: buildWaiterFunction,
      logRetention: logs.RetentionDays.ONE_DAY,
    });

    // Custom resource that waits for build completion
    const buildWaiter = new cdk.CustomResource(this, 'BuildWaiter', {
      serviceToken: buildWaiterProvider.serviceToken,
      properties: {
        BuildId: triggerBuild.getResponseField('build.id'),
        // Force update when source changes
        Timestamp: Date.now().toString(),
      },
    });

    // Ensure waiter runs after build is triggered
    buildWaiter.node.addDependency(triggerBuild);


    // ========================================================================
    // Task 10.4: Create CfnRuntime for AgentCore
    // Requirements: 15.4, 15.5, 15.6, 15.7
    // ========================================================================
    
    // Create the AgentCore Runtime using CfnRuntime
    this.agentRuntime = new bedrockagentcore.CfnRuntime(this, 'AgentRuntime', {
      agentRuntimeName: config.agentRuntimeName,
      description: `AgentCore Runtime for ${config.appName}`,
      
      // Container artifact configuration (Requirement 15.5)
      agentRuntimeArtifact: {
        containerConfiguration: {
          containerUri: `${agentRepositoryUri}:latest`,
        },
      },
      
      // Network configuration - PUBLIC mode for internet access (Requirement 15.7)
      networkConfiguration: {
        networkMode: 'PUBLIC',
      },
      
      // IAM role for the runtime
      roleArn: agentRuntimeRoleArn,
      
      // Protocol configuration
      protocolConfiguration: 'HTTP',
      
      // Environment variables (Requirement 15.6)
      // MEMORY_ID is the actual AgentCore Memory resource ID from the Memory stack
      environmentVariables: {
        AWS_REGION: this.region,
        LOG_LEVEL: 'INFO',
        MEMORY_ID: memoryId,
        GUARDRAIL_ID: guardrailId,
        GUARDRAIL_VERSION: guardrailVersion,
        KB_ID: knowledgeBaseId,
      },
      
      // Tags
      tags: {
        Application: config.appName,
        ManagedBy: 'CDK',
      },
    });

    // Ensure runtime is created after build completes
    this.agentRuntime.node.addDependency(buildWaiter);

    // ========================================================================
    // Task 10.5: Add stack outputs and exports
    // Requirements: 15.8
    // ========================================================================
    
    // Export Agent Runtime ARN
    new cdk.CfnOutput(this, 'AgentRuntimeArn', {
      value: this.agentRuntime.attrAgentRuntimeArn,
      description: 'AgentCore Runtime ARN',
      exportName: exportNames.agentRuntimeArn,
    });

    // Export Agent Runtime ID (useful for endpoint creation)
    new cdk.CfnOutput(this, 'AgentRuntimeId', {
      value: this.agentRuntime.attrAgentRuntimeId,
      description: 'AgentCore Runtime ID',
    });

    // Export Agent Runtime Version
    new cdk.CfnOutput(this, 'AgentRuntimeVersion', {
      value: this.agentRuntime.attrAgentRuntimeVersion,
      description: 'AgentCore Runtime Version',
    });
  }
}
