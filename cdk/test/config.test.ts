/**
 * Tests for the centralized configuration module.
 * 
 * With the consolidated 4-stack architecture, exportNames only includes
 * cross-stack exports needed between Foundation, Bedrock, Agent, and ChatApp stacks.
 */

import { config, validateConfig, exportNames } from '../lib/config';

describe('Config Module', () => {
  describe('config object', () => {
    test('has required base properties', () => {
      expect(config.appName).toBeDefined();
      expect(config.region).toBeDefined();
    });

    test('has DynamoDB table names', () => {
      expect(config.usageTableName).toBeDefined();
      expect(config.feedbackTableName).toBeDefined();
      expect(config.guardrailTableName).toBeDefined();
      expect(config.promptTemplatesTableName).toBeDefined();
    });

    test('has ECS configuration', () => {
      expect(config.cpu).toBeGreaterThan(0);
      expect(config.memory).toBeGreaterThan(0);
      expect(config.minTasks).toBeGreaterThanOrEqual(1);
      expect(config.maxTasks).toBeGreaterThanOrEqual(config.minTasks);
      expect(config.containerPort).toBeGreaterThan(0);
    });
  });

  describe('exportNames', () => {
    test('has Foundation stack exports (used by ChatApp)', () => {
      expect(exportNames.executionRoleArn).toContain(config.appName);
      expect(exportNames.taskRoleArn).toContain(config.appName);
      expect(exportNames.infrastructureRoleArn).toContain(config.appName);
      expect(exportNames.secretArn).toContain(config.appName);
    });

    test('has Bedrock stack exports (used by Agent)', () => {
      expect(exportNames.guardrailId).toContain(config.appName);
      expect(exportNames.guardrailVersion).toContain(config.appName);
      expect(exportNames.knowledgeBaseId).toContain(config.appName);
      expect(exportNames.memoryId).toContain(config.appName);
      expect(exportNames.memoryArn).toContain(config.appName);
    });

    test('has Agent stack exports (used by deploy scripts)', () => {
      expect(exportNames.agentRuntimeArn).toContain(config.appName);
    });

    test('has ChatApp stack exports (terminal outputs)', () => {
      expect(exportNames.serviceUrl).toContain(config.appName);
      expect(exportNames.serviceArn).toContain(config.appName);
      expect(exportNames.chatappRepositoryUri).toContain(config.appName);
    });
  });

  describe('validateConfig', () => {
    test('throws error when account is missing', () => {
      const originalAccount = config.account;
      (config as any).account = '';
      expect(() => validateConfig()).toThrow('AWS account ID is required');
      (config as any).account = originalAccount;
    });
  });
});
