/**
 * Observability Stack - CloudWatch Logs and X-Ray delivery for AgentCore Runtime and Memory.
 * 
 * This stack creates:
 * - CloudWatch Log Groups for vended logs (Runtime and Memory)
 * - Delivery sources for logs and traces (Runtime and Memory)
 * - Delivery destinations for CloudWatch Logs and X-Ray
 * - Deliveries connecting sources to destinations
 * - Resource policy for X-Ray Transaction Search
 * 
 * Exports:
 * - RuntimeLogGroupArn
 * - MemoryLogGroupArn
 */

import * as cdk from 'aws-cdk-lib';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Construct } from 'constructs';
import { config, exportNames } from './config';

export class ObservabilityStack extends cdk.Stack {
  /** The CloudWatch Log Group for Runtime logs */
  public readonly logGroup: logs.LogGroup;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Import Runtime ARN from AgentRuntime stack
    const runtimeArn = cdk.Fn.importValue(exportNames.agentRuntimeArn);
    
    // Import Memory ARN from Memory stack
    const memoryArn = cdk.Fn.importValue(exportNames.memoryArn);
    
    // Use deterministic names based on the app name since we can't parse ARNs at synth time
    const runtimeId = `${config.appName}-runtime`;
    const memoryId = `${config.appName}-memory`;

    // ========================================================================
    // CloudWatch Log Group for vended logs
    // ========================================================================
    
    this.logGroup = new logs.LogGroup(this, 'RuntimeLogGroup', {
      logGroupName: `/aws/vendedlogs/bedrock-agentcore/runtime/${runtimeId}`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ========================================================================
    // Delivery Source for Application Logs
    // ========================================================================
    
    const logsDeliverySource = new logs.CfnDeliverySource(this, 'LogsDeliverySource', {
      name: `${runtimeId}-logs-source`,
      logType: 'APPLICATION_LOGS',
      resourceArn: runtimeArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });

    // ========================================================================
    // Delivery Source for Traces
    // ========================================================================
    
    const tracesDeliverySource = new logs.CfnDeliverySource(this, 'TracesDeliverySource', {
      name: `${runtimeId}-traces-source`,
      logType: 'TRACES',
      resourceArn: runtimeArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });

    // ========================================================================
    // Delivery Destination for CloudWatch Logs
    // ========================================================================
    
    const logsDeliveryDestination = new logs.CfnDeliveryDestination(this, 'LogsDeliveryDestination', {
      name: `${runtimeId}-logs-destination`,
      deliveryDestinationType: 'CWL',
      destinationResourceArn: this.logGroup.logGroupArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });

    // ========================================================================
    // Delivery Destination for X-Ray Traces
    // ========================================================================
    
    const tracesDeliveryDestination = new logs.CfnDeliveryDestination(this, 'TracesDeliveryDestination', {
      name: `${runtimeId}-traces-destination`,
      deliveryDestinationType: 'XRAY',
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });

    // ========================================================================
    // Delivery: Connect Logs Source to CloudWatch Logs Destination
    // ========================================================================
    
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

    // ========================================================================
    // Delivery: Connect Traces Source to X-Ray Destination
    // ========================================================================
    
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
    const memoryLogGroup = new logs.LogGroup(this, 'MemoryLogGroup', {
      logGroupName: `/aws/vendedlogs/bedrock-agentcore/memory/${memoryId}`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Delivery Source for Memory Application Logs
    const memoryLogsDeliverySource = new logs.CfnDeliverySource(this, 'MemoryLogsDeliverySource', {
      name: `${memoryId}-logs-source`,
      logType: 'APPLICATION_LOGS',
      resourceArn: memoryArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });

    // Delivery Source for Memory Traces
    const memoryTracesDeliverySource = new logs.CfnDeliverySource(this, 'MemoryTracesDeliverySource', {
      name: `${memoryId}-traces-source`,
      logType: 'TRACES',
      resourceArn: memoryArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });

    // Delivery Destination for Memory CloudWatch Logs
    const memoryLogsDeliveryDestination = new logs.CfnDeliveryDestination(this, 'MemoryLogsDeliveryDestination', {
      name: `${memoryId}-logs-destination`,
      deliveryDestinationType: 'CWL',
      destinationResourceArn: memoryLogGroup.logGroupArn,
      tags: [
        { key: 'Application', value: config.appName },
        { key: 'ManagedBy', value: 'CDK' },
      ],
    });

    // Delivery Destination for Memory X-Ray Traces (reuse the same X-Ray destination type)
    const memoryTracesDeliveryDestination = new logs.CfnDeliveryDestination(this, 'MemoryTracesDeliveryDestination', {
      name: `${memoryId}-traces-destination`,
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
    
    // Create resource policy allowing X-Ray to write to CloudWatch Logs
    // This enables CloudWatch Transaction Search feature
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
    
    // Lambda function to configure X-Ray settings idempotently
    // Handles "already enabled" errors gracefully
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
    """
    Configure X-Ray Transaction Search and sampling.
    Handles "already enabled" errors gracefully.
    """
    print(f"Event: {json.dumps(event)}")
    
    # Handle Delete - just succeed (these are account-level settings)
    if event['RequestType'] == 'Delete':
        cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
        return
    
    try:
        xray = boto3.client('xray')
        results = {}
        
        # Enable Transaction Search (CloudWatch Logs destination)
        try:
            xray.update_trace_segment_destination(Destination='CloudWatchLogs')
            results['TransactionSearch'] = 'Enabled'
        except Exception as e:
            if 'already' in str(e).lower():
                results['TransactionSearch'] = 'Already enabled'
            else:
                raise e
        
        # Set sampling to 100% for POC/starter apps
        try:
            xray.update_indexing_rule(
                Name='Default',
                Rule={'Probabilistic': {'DesiredSamplingPercentage': 100}}
            )
            results['Sampling'] = 'Set to 100%'
        except Exception as e:
            # Sampling rule update failures are non-fatal
            results['Sampling'] = f'Warning: {str(e)}'
        
        print(f"Results: {json.dumps(results)}")
        cfnresponse.send(event, context, cfnresponse.SUCCESS, results)
        
    except Exception as e:
        print(f"Error: {str(e)}")
        cfnresponse.send(event, context, cfnresponse.FAILED, {}, reason=str(e))
`),
    });

    // Grant X-Ray permissions for Transaction Search
    // See: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Enable-TransactionSearch.html
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

    // Grant CloudWatch Logs permissions for log groups
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

    // Grant resource policy permissions for CloudWatch Logs
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

    // Grant Application Signals permissions
    xrayConfigFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'TransactionSearchApplicationSignalsPermissions',
        effect: iam.Effect.ALLOW,
        actions: ['application-signals:StartDiscovery'],
        resources: ['*'],
      })
    );

    // Grant permission to create service-linked role for Application Signals
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

    // Grant permission to get service-linked role
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

    // Grant CloudTrail permissions for Application Signals
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

    // Create custom resource provider
    const xrayConfigProvider = new cr.Provider(this, 'XRayConfigProvider', {
      onEventHandler: xrayConfigFunction,
      logGroup: new logs.LogGroup(this, 'XRayConfigLogs', {
        retention: logs.RetentionDays.ONE_DAY,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });

    // Custom resource to configure X-Ray
    new cdk.CustomResource(this, 'XRayConfig', {
      serviceToken: xrayConfigProvider.serviceToken,
      properties: {
        // Force update on stack updates
        Timestamp: Date.now().toString(),
      },
    });

    // ========================================================================
    // Stack Outputs
    // ========================================================================
    
    new cdk.CfnOutput(this, 'RuntimeLogGroupArn', {
      value: this.logGroup.logGroupArn,
      description: 'CloudWatch Log Group ARN for Runtime logs',
    });

    new cdk.CfnOutput(this, 'RuntimeLogGroupName', {
      value: this.logGroup.logGroupName!,
      description: 'CloudWatch Log Group name for Runtime logs',
    });

    new cdk.CfnOutput(this, 'MemoryLogGroupArn', {
      value: memoryLogGroup.logGroupArn,
      description: 'CloudWatch Log Group ARN for Memory logs',
    });

    new cdk.CfnOutput(this, 'MemoryLogGroupName', {
      value: memoryLogGroup.logGroupName!,
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
  }
}
