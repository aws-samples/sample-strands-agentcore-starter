#!/usr/bin/env node
/**
 * CDK App Entry Point for AgentCore Chat Application.
 * 
 * This file defines the stack instantiation order and dependencies.
 * The application uses 4 consolidated stacks:
 * 
 * 1. Foundation Stack - Cognito, DynamoDB, IAM roles, Secrets Manager
 * 2. Bedrock Stack - Guardrail, Knowledge Base, Memory
 * 3. Agent Stack - ECR, CodeBuild, CfnRuntime, Observability
 * 4. ChatApp Stack - ECS Express Mode service
 * 
 * Stack Deployment Order:
 * 1. Foundation - Auth, Storage, IAM, Secrets (no dependencies)
 * 2. Bedrock - Guardrail, Knowledge Base, Memory (depends on Foundation for secret updates)
 * 3. Agent - ECR, CodeBuild, Runtime, Observability (depends on Bedrock, Foundation)
 * 4. ChatApp - ECS Express Mode (depends on Foundation, Agent)
 */

import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { Aspects } from 'aws-cdk-lib';
import { AwsSolutionsChecks } from 'cdk-nag';
import { config, validateConfig, setDeploymentMode } from '../lib/config';

// Import consolidated stack classes
import { FoundationStack } from '../lib/foundation-stack';
import { BedrockStack } from '../lib/bedrock-stack';
import { AgentStack } from '../lib/agent-stack';
import { ChatAppStack } from '../lib/chatapp-stack';

// Validate configuration before synthesis
validateConfig();

const app = new cdk.App();

// Apply cdk-nag AWS Solutions checks to all stacks
Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }));

// Get deployment mode from CDK context (set via --context ingress=<mode>)
const ingressMode = app.node.tryGetContext('ingress') || 'ecs';
setDeploymentMode(ingressMode);

// Environment configuration from CDK context or environment variables
const env: cdk.Environment = {
  account: config.account || process.env.CDK_DEFAULT_ACCOUNT,
  region: config.region || process.env.CDK_DEFAULT_REGION || 'us-east-1',
};

// ============================================================================
// Foundation Stack - Auth, Storage, IAM, Secrets (no dependencies)
// ============================================================================

const foundationStack = new FoundationStack(app, `${config.appName}-Foundation`, {
  env,
  description: 'AgentCore Chat App: Cognito, DynamoDB, IAM roles, and Secrets Manager',
  stackName: `${config.appName}-foundation`,
});

// ============================================================================
// Bedrock Stack - Guardrail, Knowledge Base, Memory (depends on Foundation for secret)
// ============================================================================

const bedrockStack = new BedrockStack(app, `${config.appName}-Bedrock`, {
  env,
  description: 'AgentCore Chat App: Bedrock Guardrail, Knowledge Base, and Memory',
  stackName: `${config.appName}-bedrock`,
});
bedrockStack.addDependency(foundationStack);

// ============================================================================
// Agent Stack - ECR, CodeBuild, Runtime, Observability (depends on Bedrock, Foundation)
// ============================================================================

const agentStack = new AgentStack(app, `${config.appName}-Agent`, {
  env,
  description: 'AgentCore Chat App: Agent infrastructure, runtime, and observability',
  stackName: `${config.appName}-agent`,
});
agentStack.addDependency(bedrockStack);
agentStack.addDependency(foundationStack);

// ============================================================================
// ChatApp Stack - ECS Express Mode (depends on Foundation, Agent)
// ============================================================================

const chatAppStack = new ChatAppStack(app, `${config.appName}-ChatApp`, {
  env,
  description: 'AgentCore Chat App: ECS Express Mode service for chat application',
  stackName: `${config.appName}-chatapp`,
});
chatAppStack.addDependency(foundationStack);
chatAppStack.addDependency(agentStack);

// ============================================================================
// Add tags to all stacks
// ============================================================================

const stacks = [
  foundationStack,
  bedrockStack,
  agentStack,
  chatAppStack,
];

stacks.forEach((stack) => {
  cdk.Tags.of(stack).add('Application', config.appName);
  cdk.Tags.of(stack).add('ManagedBy', 'CDK');
});

app.synth();
