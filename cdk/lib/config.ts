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
 */
export const exportNames = {
  // Auth stack exports
  userPoolId: `${config.appName}-UserPoolId`,
  userPoolArn: `${config.appName}-UserPoolArn`,
  userPoolClientId: `${config.appName}-UserPoolClientId`,

  // Storage stack exports
  usageTableName: `${config.appName}-UsageTableName`,
  usageTableArn: `${config.appName}-UsageTableArn`,
  feedbackTableName: `${config.appName}-FeedbackTableName`,
  feedbackTableArn: `${config.appName}-FeedbackTableArn`,
  guardrailTableName: `${config.appName}-GuardrailTableName`,
  guardrailTableArn: `${config.appName}-GuardrailTableArn`,
  promptTemplatesTableName: `${config.appName}-PromptTemplatesTableName`,
  promptTemplatesTableArn: `${config.appName}-PromptTemplatesTableArn`,

  // Guardrail stack exports
  guardrailId: `${config.appName}-GuardrailId`,
  guardrailVersion: `${config.appName}-GuardrailVersion`,
  guardrailArn: `${config.appName}-GuardrailArn`,

  // Knowledge Base stack exports
  knowledgeBaseId: `${config.appName}-KnowledgeBaseId`,
  knowledgeBaseArn: `${config.appName}-KnowledgeBaseArn`,
  kbSourceBucketName: `${config.appName}-KBSourceBucketName`,

  // IAM stack exports
  executionRoleArn: `${config.appName}-ExecutionRoleArn`,
  taskRoleArn: `${config.appName}-TaskRoleArn`,
  infrastructureRoleArn: `${config.appName}-InfrastructureRoleArn`,

  // Agent Infrastructure stack exports
  agentRepositoryUri: `${config.appName}-AgentRepositoryUri`,
  agentRuntimeRoleArn: `${config.appName}-AgentRuntimeRoleArn`,
  buildSourceBucketName: `${config.appName}-BuildSourceBucketName`,
  buildProjectName: `${config.appName}-BuildProjectName`,
  buildProjectArn: `${config.appName}-BuildProjectArn`,

  // Memory stack exports
  memoryId: `${config.appName}-MemoryId`,
  memoryArn: `${config.appName}-MemoryArn`,

  // Agent Runtime stack exports
  agentRuntimeArn: `${config.appName}-AgentRuntimeArn`,
  agentRuntimeEndpoint: `${config.appName}-AgentRuntimeEndpoint`,

  // Secrets stack exports
  secretArn: `${config.appName}-SecretArn`,

  // ChatApp stack exports
  serviceUrl: `${config.appName}-ServiceUrl`,
  serviceArn: `${config.appName}-ServiceArn`,
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
