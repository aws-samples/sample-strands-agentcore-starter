/**
 * Memory Stack - AgentCore Memory resource for conversation persistence.
 * 
 * This stack creates:
 * - CfnMemory resource with event and semantic memory strategies
 * 
 * Exports:
 * - MemoryId
 * - MemoryArn
 */

import * as cdk from 'aws-cdk-lib';
import * as bedrockagentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import { Construct } from 'constructs';
import { config, exportNames } from './config';

export class MemoryStack extends cdk.Stack {
  /** The AgentCore Memory resource */
  public readonly memory: bedrockagentcore.CfnMemory;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ========================================================================
    // Create AgentCore Memory with semantic strategies
    // ========================================================================
    
    // Memory name must match pattern: ^[a-zA-Z][a-zA-Z0-9_]{0,47}$
    // Replace hyphens with underscores
    const memoryName = `${config.appName.replace(/-/g, '_')}_memory`;
    
    this.memory = new bedrockagentcore.CfnMemory(this, 'AgentMemory', {
      name: memoryName,
      description: `AgentCore Memory for ${config.appName} conversation persistence`,
      
      // Event retention: 30 days for short-term memory
      eventExpiryDuration: 30,
      
      // Memory strategies for long-term memory extraction
      memoryStrategies: [
        {
          // Summary strategy - creates session summaries
          summaryMemoryStrategy: {
            name: 'SessionSummarizer',
            namespaces: ['/summaries/{actorId}/{sessionId}'],
          },
        },
        {
          // User preference strategy - extracts user preferences
          userPreferenceMemoryStrategy: {
            name: 'PreferenceLearner',
            namespaces: ['/users/{actorId}/preferences'],
          },
        },
        {
          // Semantic fact strategy - extracts facts from conversations
          semanticMemoryStrategy: {
            name: 'FactExtractor',
            namespaces: ['/users/{actorId}/facts'],
          },
        },
      ],
      
      // Tags
      tags: {
        Application: config.appName,
        ManagedBy: 'CDK',
      },
    });

    // ========================================================================
    // Stack outputs and exports
    // ========================================================================
    
    // Export Memory ID
    new cdk.CfnOutput(this, 'MemoryId', {
      value: this.memory.attrMemoryId,
      description: 'AgentCore Memory ID',
      exportName: exportNames.memoryId,
    });

    // Export Memory ARN
    new cdk.CfnOutput(this, 'MemoryArn', {
      value: this.memory.attrMemoryArn,
      description: 'AgentCore Memory ARN',
      exportName: exportNames.memoryArn,
    });
  }
}
