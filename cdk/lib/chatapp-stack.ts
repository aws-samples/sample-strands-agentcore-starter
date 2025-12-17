/**
 * ChatApp Stack - ECS Express Mode service for the chat application.
 * 
 * This stack creates:
 * - CloudWatch log group for container logs
 * - ECS Express Gateway Service with auto-scaling
 * - Custom resource to update deployment configuration
 * 
 * Note: ECR repository is created by deploy-all.sh before this stack runs
 * to ensure the image exists before the ECS service is created.
 * 
 * Exports:
 * - ServiceUrl
 * - ServiceArn
 * - ChatAppRepositoryUri
 */

import * as cdk from 'aws-cdk-lib';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as cr from 'aws-cdk-lib/custom-resources';
import { Construct } from 'constructs';
import { config, exportNames } from './config';

export class ChatAppStack extends cdk.Stack {
  /** ECR repository for chat application container images (imported) */
  public readonly chatappRepository: ecr.IRepository;
  
  /** CloudWatch log group for container logs */
  public readonly logGroup: logs.LogGroup;
  
  /** ECS Express Gateway Service */
  public readonly expressGatewayService: ecs.CfnExpressGatewayService;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ========================================================================
    // Task 13.1: Import ECR repository for chat application container images
    // Requirements: 8.1
    // Note: Repository is created by deploy-all.sh before CDK deployment
    // ========================================================================
    
    // Import existing ECR repository (created by deploy-all.sh)
    this.chatappRepository = ecr.Repository.fromRepositoryName(
      this,
      'ChatAppRepository',
      config.chatappRepoName
    );


    // ========================================================================
    // Task 13.2: Create CloudWatch log group for container logs
    // Requirements: 8.6
    // ========================================================================
    
    this.logGroup = new logs.LogGroup(this, 'ChatAppLogGroup', {
      logGroupName: `/ecs/${config.appName}/${config.ecsServiceName}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      retention: logs.RetentionDays.ONE_WEEK,
    });

    // ========================================================================
    // Task 13.3: Create ECS Express Gateway Service
    // Requirements: 8.2, 8.3, 8.4, 8.5
    // ========================================================================
    
    // Import IAM roles from IAM stack
    const executionRoleArn = cdk.Fn.importValue(exportNames.executionRoleArn);
    const taskRoleArn = cdk.Fn.importValue(exportNames.taskRoleArn);
    const infrastructureRoleArn = cdk.Fn.importValue(exportNames.infrastructureRoleArn);
    
    // Import secret ARN from Secrets stack
    const secretArn = cdk.Fn.importValue(exportNames.secretArn);

    // Create ECS Express Gateway Service
    this.expressGatewayService = new ecs.CfnExpressGatewayService(this, 'ExpressGatewayService', {
      serviceName: config.ecsServiceName,
      
      // IAM roles (Requirements: 8.2)
      executionRoleArn: executionRoleArn.toString(),
      infrastructureRoleArn: infrastructureRoleArn.toString(),
      taskRoleArn: taskRoleArn.toString(),
      
      // Resource allocation (Requirements: 8.2)
      cpu: config.cpu.toString(),
      memory: config.memory.toString(),
      
      // Health check configuration (Requirements: 8.4)
      healthCheckPath: '/health',
      
      // Auto-scaling configuration (Requirements: 8.3)
      scalingTarget: {
        minTaskCount: config.minTasks,
        maxTaskCount: config.maxTasks,
        autoScalingMetric: 'AVERAGE_CPU',
        autoScalingTargetValue: 70,
      },
      
      // Primary container configuration (Requirements: 8.5)
      primaryContainer: {
        image: `${this.chatappRepository.repositoryUri}:latest`,
        containerPort: config.containerPort,
        
        // CloudWatch Logs configuration
        awsLogsConfiguration: {
          logGroup: this.logGroup.logGroupName,
          logStreamPrefix: 'chatapp',
        },
        
        // Inject secrets as environment variables (Requirements: 8.5)
        secrets: [
          {
            name: 'COGNITO_USER_POOL_ID',
            valueFrom: `${secretArn}:cognito_user_pool_id::`,
          },
          {
            name: 'COGNITO_CLIENT_ID',
            valueFrom: `${secretArn}:cognito_client_id::`,
          },
          {
            name: 'COGNITO_CLIENT_SECRET',
            valueFrom: `${secretArn}:cognito_client_secret::`,
          },
          {
            name: 'AGENTCORE_RUNTIME_ARN',
            valueFrom: `${secretArn}:agentcore_runtime_arn::`,
          },
          {
            name: 'MEMORY_ID',
            valueFrom: `${secretArn}:memory_id::`,
          },
          {
            name: 'USAGE_TABLE_NAME',
            valueFrom: `${secretArn}:usage_table_name::`,
          },
          {
            name: 'FEEDBACK_TABLE_NAME',
            valueFrom: `${secretArn}:feedback_table_name::`,
          },
          {
            name: 'GUARDRAIL_TABLE_NAME',
            valueFrom: `${secretArn}:guardrail_table_name::`,
          },
          {
            name: 'PROMPT_TEMPLATES_TABLE_NAME',
            valueFrom: `${secretArn}:prompt_templates_table_name::`,
          },
          {
            name: 'GUARDRAIL_ID',
            valueFrom: `${secretArn}:guardrail_id::`,
          },
          {
            name: 'GUARDRAIL_VERSION',
            valueFrom: `${secretArn}:guardrail_version::`,
          },
          {
            name: 'KB_ID',
            valueFrom: `${secretArn}:kb_id::`,
          },
        ],
        
        // Environment variables (non-secret)
        environment: [
          {
            name: 'AWS_REGION',
            value: this.region,
          },
          {
            name: 'PORT',
            value: config.containerPort.toString(),
          },
          {
            name: 'LOG_LEVEL',
            value: 'INFO',
          },
        ],
      },
    });

    // Ensure the service depends on the log group
    this.expressGatewayService.node.addDependency(this.logGroup);


    // ========================================================================
    // Task 13.4: Create deployment configuration update custom resource
    // Requirements: 8.7
    // ========================================================================
    
    // Custom resource to update ECS service deployment configuration
    // This sets bakeTimeInMinutes=0 and canaryPercent=100 for faster deployments
    const updateDeploymentConfig = new cr.AwsCustomResource(this, 'UpdateDeploymentConfig', {
      onCreate: {
        service: 'ECS',
        action: 'updateService',
        parameters: {
          cluster: 'default',
          service: config.ecsServiceName,
          deploymentConfiguration: {
            bakeTimeInMinutes: 0,
            canaryConfiguration: {
              canaryPercent: 100.0,
              canaryBakeTimeInMinutes: 0,
            },
          },
        },
        physicalResourceId: cr.PhysicalResourceId.of(`${config.ecsServiceName}-deployment-config`),
      },
      onUpdate: {
        service: 'ECS',
        action: 'updateService',
        parameters: {
          cluster: 'default',
          service: config.ecsServiceName,
          deploymentConfiguration: {
            bakeTimeInMinutes: 0,
            canaryConfiguration: {
              canaryPercent: 100.0,
              canaryBakeTimeInMinutes: 0,
            },
          },
        },
        physicalResourceId: cr.PhysicalResourceId.of(`${config.ecsServiceName}-deployment-config`),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['ecs:UpdateService'],
          resources: [
            `arn:aws:ecs:${this.region}:${this.account}:service/default/${config.ecsServiceName}`,
          ],
        }),
      ]),
    });

    // Ensure this runs after the Express Gateway Service is created
    updateDeploymentConfig.node.addDependency(this.expressGatewayService);

    // ========================================================================
    // Task 13.5: Add stack outputs and exports
    // Requirements: 8.9
    // ========================================================================
    
    // Export ECR repository URI
    new cdk.CfnOutput(this, 'ChatAppRepositoryUri', {
      value: this.chatappRepository.repositoryUri,
      description: 'ECR repository URI for chat application container images',
      exportName: exportNames.chatappRepositoryUri,
    });

    // Note: The actual service URL is not available as a CloudFormation attribute.
    // The deploy-all.sh script fetches the real URL from the ECS API after deployment.
    // This output provides a placeholder that indicates where to find the URL.
    new cdk.CfnOutput(this, 'ServiceName', {
      value: config.ecsServiceName,
      description: 'ECS Express Mode service name (use deploy-all.sh to get actual URL)',
      exportName: exportNames.serviceUrl,
    });

    // Export Service ARN
    new cdk.CfnOutput(this, 'ServiceArn', {
      value: this.expressGatewayService.attrServiceArn,
      description: 'ECS Express Gateway Service ARN',
      exportName: exportNames.serviceArn,
    });

    // Output log group name for reference
    new cdk.CfnOutput(this, 'LogGroupName', {
      value: this.logGroup.logGroupName,
      description: 'CloudWatch log group name for container logs',
    });
  }
}
