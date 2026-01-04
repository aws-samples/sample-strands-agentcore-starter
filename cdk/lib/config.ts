/**
 * Centralized configuration for AgentCore Chat Application CDK stacks.
 * 
 * This module defines all resource naming conventions and environment settings
 * used across the CDK stacks. Configuration can be overridden via environment
 * variables for deployment to different environments.
 */

/**
 * Application configuration interface defining all resource naming conventions
 * and deployment settings.
 */
export interface AppConfig {
  /** Base name for resources (e.g., "htmx-chatapp") */
  appName: string;
  
  /** AWS region for deployment */
  region: string;
  
  /** AWS account ID */
  account: string;

  // Cognito configuration
  /** Cognito User Pool name */
  cognitoPoolName: string;
  
  // DynamoDB table names
  /** Usage records table name */
  usageTableName: string;
  /** Feedback table name */
  feedbackTableName: string;
  /** Guardrail violations table name */
  guardrailTableName: string;
  /** Prompt templates table name */
  promptTemplatesTableName: string;
  /** App settings table name */
  appSettingsTableName: string;
  /** Runtime usage table name */
  runtimeUsageTableName: string;

  // Bedrock configuration
  /** Bedrock Guardrail name */
  guardrailName: string;
  /** Knowledge Base name */
  kbName: string;
  /** Knowledge Base source bucket name */
  kbSourceBucketName: string;

  // Secrets configuration
  /** Secrets Manager secret name */
  secretName: string;

  // ECS configuration
  /** ECS service name */
  ecsServiceName: string;
  /** CPU units for ECS tasks */
  cpu: number;
  /** Memory in MB for ECS tasks */
  memory: number;
  /** Minimum number of ECS tasks */
  minTasks: number;
  /** Maximum number of ECS tasks */
  maxTasks: number;
  /** Container port */
  containerPort: number;

  // ECR configuration
  /** Agent ECR repository name */
  agentRepoName: string;
  /** ChatApp ECR repository name */
  chatappRepoName: string;

  // CodeBuild configuration
  /** CodeBuild project name for agent builds */
  agentBuildProjectName: string;
  /** S3 bucket name for CodeBuild source */
  buildSourceBucketName: string;

  // AgentCore configuration
  /** AgentCore Runtime name */
  agentRuntimeName: string;
}

/**
 * Get configuration value from environment variable or use default.
 * @param envVar - Environment variable name
 * @param defaultValue - Default value if env var is not set
 * @returns The environment variable value or default
 */
function getEnvOrDefault(envVar: string, defaultValue: string): string {
  return process.env[envVar] || defaultValue;
}

/**
 * Get numeric configuration value from environment variable or use default.
 * @param envVar - Environment variable name
 * @param defaultValue - Default value if env var is not set
 * @returns The parsed number or default
 */
function getEnvNumberOrDefault(envVar: string, defaultValue: number): number {
  const value = process.env[envVar];
  if (value) {
    const parsed = parseInt(value, 10);
    return isNaN(parsed) ? defaultValue : parsed;
  }
  return defaultValue;
}

/**
 * Default application configuration.
 * Values can be overridden via environment variables.
 */
export const config: AppConfig = {
  // Base configuration
  appName: getEnvOrDefault('APP_NAME', 'htmx-chatapp'),
  region: getEnvOrDefault('AWS_REGION', getEnvOrDefault('CDK_DEFAULT_REGION', 'us-east-1')),
  account: getEnvOrDefault('AWS_ACCOUNT_ID', getEnvOrDefault('CDK_DEFAULT_ACCOUNT', '')),

  // Cognito configuration
  cognitoPoolName: getEnvOrDefault('COGNITO_POOL_NAME', 'htmx-chatapp-users'),

  // DynamoDB table names
  usageTableName: getEnvOrDefault('USAGE_TABLE_NAME', 'agentcore-usage-records'),
  feedbackTableName: getEnvOrDefault('FEEDBACK_TABLE_NAME', 'agentcore-feedback'),
  guardrailTableName: getEnvOrDefault('GUARDRAIL_TABLE_NAME', 'agentcore-guardrail-violations'),
  promptTemplatesTableName: getEnvOrDefault('PROMPT_TEMPLATES_TABLE_NAME', 'agentcore-prompt-templates'),
  appSettingsTableName: getEnvOrDefault('APP_SETTINGS_TABLE_NAME', 'agentcore-app-settings'),
  runtimeUsageTableName: getEnvOrDefault('RUNTIME_USAGE_TABLE_NAME', 'agentcore-runtime-usage'),

  // Bedrock configuration
  guardrailName: getEnvOrDefault('GUARDRAIL_NAME', 'agentcore-chatapp-guardrail'),
  kbName: getEnvOrDefault('KB_NAME', 'htmx-chatapp-kb'),
  kbSourceBucketName: getEnvOrDefault('KB_SOURCE_BUCKET_NAME', 'htmx-chatapp-kb-source'),

  // Secrets configuration
  secretName: getEnvOrDefault('SECRET_NAME', 'htmx-chatapp/config'),

  // ECS configuration
  ecsServiceName: getEnvOrDefault('ECS_SERVICE_NAME', 'htmx-chatapp-express'),
  cpu: getEnvNumberOrDefault('ECS_CPU', 512),
  memory: getEnvNumberOrDefault('ECS_MEMORY', 1024),
  minTasks: getEnvNumberOrDefault('ECS_MIN_TASKS', 1),
  maxTasks: getEnvNumberOrDefault('ECS_MAX_TASKS', 10),
  containerPort: getEnvNumberOrDefault('CONTAINER_PORT', 8080),

  // ECR configuration
  agentRepoName: getEnvOrDefault('AGENT_REPO_NAME', 'htmx-chatapp-agent'),
  chatappRepoName: getEnvOrDefault('CHATAPP_REPO_NAME', 'htmx-chatapp'),

  // CodeBuild configuration
  agentBuildProjectName: getEnvOrDefault('AGENT_BUILD_PROJECT_NAME', 'htmx-chatapp-agent-build'),
  buildSourceBucketName: getEnvOrDefault('BUILD_SOURCE_BUCKET_NAME', 'htmx-chatapp-build-source'),

  // AgentCore configuration
  agentRuntimeName: getEnvOrDefault('AGENT_RUNTIME_NAME', 'chat_app'),
};

/**
 * Stack export name prefixes for cross-stack references.
 * These are used with Fn.importValue for stack isolation.
 * 
 * With the consolidated 4-stack architecture:
 * - Foundation Stack: Auth, Storage, IAM, Secrets
 * - Bedrock Stack: Guardrail, Knowledge Base, Memory
 * - Agent Stack: Agent Infrastructure, Runtime, Observability
 * - ChatApp Stack: ECS Express Mode service
 * 
 * Only exports needed for cross-stack references are defined here.
 * Internal resources within a stack use direct references.
 */
export const exportNames = {
  // ========================================================================
  // Foundation Stack exports (used by ChatApp Stack)
  // ========================================================================
  
  /** ECS task execution role ARN - used by ChatApp for container execution */
  executionRoleArn: `${config.appName}-ExecutionRoleArn`,
  /** ECS task role ARN - used by ChatApp for runtime permissions */
  taskRoleArn: `${config.appName}-TaskRoleArn`,
  /** ECS infrastructure role ARN - used by ChatApp for Express Mode */
  infrastructureRoleArn: `${config.appName}-InfrastructureRoleArn`,
  /** Secrets Manager secret ARN - used by ChatApp to inject configuration */
  secretArn: `${config.appName}-SecretArn`,

  // ========================================================================
  // Bedrock Stack exports (used by Agent Stack)
  // ========================================================================
  
  /** Bedrock Guardrail ID - used by Agent Runtime for content filtering */
  guardrailId: `${config.appName}-GuardrailId`,
  /** Bedrock Guardrail Version - used by Agent Runtime */
  guardrailVersion: `${config.appName}-GuardrailVersion`,
  /** Bedrock Knowledge Base ID - used by Agent Runtime for semantic search */
  knowledgeBaseId: `${config.appName}-KnowledgeBaseId`,
  /** AgentCore Memory ID - used by Agent Runtime for conversation persistence */
  memoryId: `${config.appName}-MemoryId`,
  /** AgentCore Memory ARN - used by Agent Stack for observability setup */
  memoryArn: `${config.appName}-MemoryArn`,

  // ========================================================================
  // Agent Stack exports (used by deploy scripts for secrets update)
  // ========================================================================
  
  /** AgentCore Runtime ARN - stored in secrets for ChatApp access */
  agentRuntimeArn: `${config.appName}-AgentRuntimeArn`,

  /** Runtime usage table ARN - used by Agent Stack for Firehose delivery */
  runtimeUsageTableArn: `${config.appName}-RuntimeUsageTableArn`,

  // ========================================================================
  // ChatApp Stack exports (terminal outputs, not used by other stacks)
  // ========================================================================
  
  /** ECS service URL placeholder - actual URL fetched by deploy script */
  serviceUrl: `${config.appName}-ServiceUrl`,
  /** ECS Express Gateway Service ARN */
  serviceArn: `${config.appName}-ServiceArn`,
  /** ECR repository URI for chat application images */
  chatappRepositoryUri: `${config.appName}-ChatAppRepositoryUri`,
};

/**
 * Validate that required configuration is present.
 * Throws an error if required values are missing.
 */
export function validateConfig(): void {
  if (!config.account) {
    throw new Error(
      'AWS account ID is required. Set CDK_DEFAULT_ACCOUNT or AWS_ACCOUNT_ID environment variable.'
    );
  }
  if (!config.region) {
    throw new Error(
      'AWS region is required. Set CDK_DEFAULT_REGION or AWS_REGION environment variable.'
    );
  }
}

export default config;
