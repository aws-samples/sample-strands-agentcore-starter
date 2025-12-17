/**
 * Tests for the centralized configuration module.
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
    test('has auth stack exports', () => {
      expect(exportNames.userPoolId).toContain(config.appName);
      expect(exportNames.userPoolArn).toContain(config.appName);
      expect(exportNames.userPoolClientId).toContain(config.appName);
    });

    test('has storage stack exports', () => {
      expect(exportNames.usageTableName).toContain(config.appName);
      expect(exportNames.feedbackTableName).toContain(config.appName);
      expect(exportNames.guardrailTableName).toContain(config.appName);
      expect(exportNames.promptTemplatesTableName).toContain(config.appName);
    });

    test('has guardrail stack exports', () => {
      expect(exportNames.guardrailId).toContain(config.appName);
      expect(exportNames.guardrailVersion).toContain(config.appName);
      expect(exportNames.guardrailArn).toContain(config.appName);
    });

    test('has knowledge base stack exports', () => {
      expect(exportNames.knowledgeBaseId).toContain(config.appName);
      expect(exportNames.knowledgeBaseArn).toContain(config.appName);
      expect(exportNames.kbSourceBucketName).toContain(config.appName);
    });

    test('has IAM stack exports', () => {
      expect(exportNames.executionRoleArn).toContain(config.appName);
      expect(exportNames.taskRoleArn).toContain(config.appName);
      expect(exportNames.infrastructureRoleArn).toContain(config.appName);
    });

    test('has agent infrastructure stack exports', () => {
      expect(exportNames.agentRepositoryUri).toContain(config.appName);
      expect(exportNames.agentRuntimeRoleArn).toContain(config.appName);
      expect(exportNames.buildSourceBucketName).toContain(config.appName);
      expect(exportNames.buildProjectName).toContain(config.appName);
    });

    test('has agent runtime stack exports', () => {
      expect(exportNames.agentRuntimeArn).toContain(config.appName);
    });

    test('has secrets stack exports', () => {
      expect(exportNames.secretArn).toContain(config.appName);
    });

    test('has chatapp stack exports', () => {
      expect(exportNames.serviceUrl).toContain(config.appName);
      expect(exportNames.serviceArn).toContain(config.appName);
    });
  });
});
