#!/usr/bin/env node
/**
 * CDK App Entry Point for AgentCore Chat Application.
 * 
 * This file defines the stack instantiation order and dependencies.
 * Stacks are organized to ensure:
 * 1. Foundational stacks (Auth, Storage, Guardrail, KB, IAM, AgentInfra) deploy first
 * 2. Application stacks (AgentRuntime, Secrets, ChatApp) depend on foundational stacks
 * 3. Observability stack configures logging and tracing after Runtime is created
 * 4. Stack isolation ensures failures don't cascade
 * 
 * Stack Deployment Order:
 * 1. Auth - Cognito User Pool (no dependencies)
 * 2. Storage - DynamoDB tables (no dependencies)
 * 3. Guardrail - Bedrock Guardrail (no dependencies)
 * 4. KnowledgeBase - S3 Vectors + Bedrock KB (no dependencies)
 * 5. Memory - AgentCore Memory (no dependencies)
 * 6. IAM - ECS task roles (depends on Storage for table ARNs)
 * 7. AgentInfra - ECR, CodeBuild, Agent IAM role (no dependencies)
 * 8. AgentRuntime - CfnRuntime (depends on AgentInfra, Guardrail, KB, Memory)
 * 9. Observability - Log delivery, X-Ray tracing (depends on AgentRuntime)
 * 10. Secrets - Secrets Manager (depends on Auth, Storage, AgentRuntime)
 * 11. ChatApp - ECS Express Mode (depends on IAM, Secrets)
 */

import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { config, validateConfig } from '../lib/config';

// Import all stack classes
import { AuthStack } from '../lib/auth-stack';
import { StorageStack } from '../lib/storage-stack';
import { GuardrailStack } from '../lib/guardrail-stack';
import { KnowledgeBaseStack } from '../lib/knowledgebase-stack';
import { MemoryStack } from '../lib/memory-stack';
import { IamStack } from '../lib/iam-stack';
import { AgentInfraStack } from '../lib/agent-infra-stack';
import { AgentRuntimeStack } from '../lib/agent-runtime-stack';
import { SecretsStack } from '../lib/secrets-stack';
import { ChatAppStack } from '../lib/chatapp-stack';
import { ObservabilityStack } from '../lib/observability-stack';

// Validate configuration before synthesis
validateConfig();

const app = new cdk.App();

// Environment configuration from CDK context or environment variables
const env: cdk.Environment = {
  account: config.account || process.env.CDK_DEFAULT_ACCOUNT,
  region: config.region || process.env.CDK_DEFAULT_REGION || 'us-east-1',
};

// ============================================================================
// Foundational Stacks (no dependencies on other stacks)
// ============================================================================

// Auth Stack - Cognito User Pool
const authStack = new AuthStack(app, `${config.appName}-Auth`, {
  env,
  description: 'AgentCore Chat App: Cognito User Pool for authentication',
  stackName: `${config.appName}-auth`,
});

// Storage Stack - DynamoDB tables
const storageStack = new StorageStack(app, `${config.appName}-Storage`, {
  env,
  description: 'AgentCore Chat App: DynamoDB tables for usage, feedback, guardrails, and templates',
  stackName: `${config.appName}-storage`,
});

// Guardrail Stack - Bedrock Guardrail
const guardrailStack = new GuardrailStack(app, `${config.appName}-Guardrail`, {
  env,
  description: 'AgentCore Chat App: Bedrock Guardrail for content filtering',
  stackName: `${config.appName}-guardrail`,
});

// Knowledge Base Stack - S3 Vectors + Bedrock KB
const knowledgeBaseStack = new KnowledgeBaseStack(app, `${config.appName}-KnowledgeBase`, {
  env,
  description: 'AgentCore Chat App: Bedrock Knowledge Base with S3 Vectors storage',
  stackName: `${config.appName}-knowledgebase`,
});

// Memory Stack - AgentCore Memory for conversation persistence
const memoryStack = new MemoryStack(app, `${config.appName}-Memory`, {
  env,
  description: 'AgentCore Chat App: AgentCore Memory for conversation persistence',
  stackName: `${config.appName}-memory`,
});

// ============================================================================
// IAM Stack (depends on Storage for table ARNs)
// ============================================================================

const iamStack = new IamStack(app, `${config.appName}-IAM`, {
  env,
  description: 'AgentCore Chat App: IAM roles for ECS tasks and execution',
  stackName: `${config.appName}-iam`,
});
// IAM stack needs exports from Auth, Storage, Guardrail, and KnowledgeBase stacks
iamStack.addDependency(authStack);
iamStack.addDependency(storageStack);
iamStack.addDependency(guardrailStack);
iamStack.addDependency(knowledgeBaseStack);

// ============================================================================
// Agent Infrastructure Stack (no dependencies)
// ============================================================================

const agentInfraStack = new AgentInfraStack(app, `${config.appName}-AgentInfra`, {
  env,
  description: 'AgentCore Chat App: ECR repository, CodeBuild project, and Agent IAM role',
  stackName: `${config.appName}-agent-infra`,
});

// ============================================================================
// Agent Runtime Stack (depends on AgentInfra, Guardrail, KnowledgeBase)
// ============================================================================

const agentRuntimeStack = new AgentRuntimeStack(app, `${config.appName}-AgentRuntime`, {
  env,
  description: 'AgentCore Chat App: AgentCore CfnRuntime deployment',
  stackName: `${config.appName}-agent-runtime`,
});
agentRuntimeStack.addDependency(agentInfraStack);
agentRuntimeStack.addDependency(guardrailStack);
agentRuntimeStack.addDependency(knowledgeBaseStack);
agentRuntimeStack.addDependency(memoryStack);

// ============================================================================
// Observability Stack (depends on AgentRuntime)
// ============================================================================

const observabilityStack = new ObservabilityStack(app, `${config.appName}-Observability`, {
  env,
  description: 'AgentCore Chat App: CloudWatch Logs and X-Ray observability',
  stackName: `${config.appName}-observability`,
});
observabilityStack.addDependency(agentRuntimeStack);

// ============================================================================
// Secrets Stack (depends on Auth, Storage, AgentRuntime)
// ============================================================================

const secretsStack = new SecretsStack(app, `${config.appName}-Secrets`, {
  env,
  description: 'AgentCore Chat App: Secrets Manager for application configuration',
  stackName: `${config.appName}-secrets`,
});
secretsStack.addDependency(authStack);
secretsStack.addDependency(storageStack);
secretsStack.addDependency(agentRuntimeStack);
secretsStack.addDependency(memoryStack);

// ============================================================================
// ChatApp Stack (depends on IAM, Secrets)
// ============================================================================

const chatAppStack = new ChatAppStack(app, `${config.appName}-ChatApp`, {
  env,
  description: 'AgentCore Chat App: ECS Express Mode service for chat application',
  stackName: `${config.appName}-chatapp`,
});
chatAppStack.addDependency(iamStack);
chatAppStack.addDependency(secretsStack);

// ============================================================================
// Add tags to all stacks
// ============================================================================

const stacks = [
  authStack,
  storageStack,
  guardrailStack,
  knowledgeBaseStack,
  memoryStack,
  iamStack,
  agentInfraStack,
  agentRuntimeStack,
  observabilityStack,
  secretsStack,
  chatAppStack,
];

stacks.forEach((stack) => {
  cdk.Tags.of(stack).add('Application', config.appName);
  cdk.Tags.of(stack).add('ManagedBy', 'CDK');
});

app.synth();
