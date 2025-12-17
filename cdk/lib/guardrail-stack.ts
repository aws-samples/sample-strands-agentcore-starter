/**
 * Guardrail Stack - Bedrock Guardrail for content filtering.
 * 
 * This stack creates a Bedrock Guardrail with content filters
 * for HATE, VIOLENCE, SEXUAL, INSULTS, and MISCONDUCT.
 * 
 * Exports:
 * - GuardrailId
 * - GuardrailVersion
 * - GuardrailArn
 */

import * as cdk from 'aws-cdk-lib';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import { Construct } from 'constructs';
import { config, exportNames } from './config';

export class GuardrailStack extends cdk.Stack {
  /** The Bedrock Guardrail */
  public readonly guardrail: bedrock.CfnGuardrail;
  
  /** The published Guardrail version */
  public readonly guardrailVersion: bedrock.CfnGuardrailVersion;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ========================================================================
    // Task 5.1: Create Bedrock Guardrail with content filters
    // Requirements: 4.1, 4.3
    // ========================================================================
    
    this.guardrail = new bedrock.CfnGuardrail(this, 'Guardrail', {
      name: config.guardrailName,
      
      // Blocked messaging (Requirement 4.3)
      blockedInputMessaging: 'Your message could not be processed due to content policy restrictions.',
      blockedOutputsMessaging: 'The response could not be provided due to content policy restrictions.',
      
      // Content policy with MEDIUM strength filters (Requirement 4.1)
      contentPolicyConfig: {
        filtersConfig: [
          {
            type: 'HATE',
            inputStrength: 'MEDIUM',
            outputStrength: 'MEDIUM',
          },
          {
            type: 'VIOLENCE',
            inputStrength: 'MEDIUM',
            outputStrength: 'MEDIUM',
          },
          {
            type: 'SEXUAL',
            inputStrength: 'MEDIUM',
            outputStrength: 'MEDIUM',
          },
          {
            type: 'INSULTS',
            inputStrength: 'MEDIUM',
            outputStrength: 'MEDIUM',
          },
          {
            type: 'MISCONDUCT',
            inputStrength: 'MEDIUM',
            outputStrength: 'MEDIUM',
          },
        ],
      },
      
      // Optional description
      description: 'Content filtering guardrail for AgentCore Chat Application',
    });

    // ========================================================================
    // Task 5.2: Create guardrail version
    // Requirement: 4.2
    // ========================================================================
    
    this.guardrailVersion = new bedrock.CfnGuardrailVersion(this, 'GuardrailVersion', {
      guardrailIdentifier: this.guardrail.attrGuardrailId,
      description: 'Version 1 - Initial production release',
    });
    
    // Ensure version is created after guardrail
    this.guardrailVersion.addDependency(this.guardrail);

    // ========================================================================
    // Task 5.3: Add stack outputs and exports
    // Requirement: 4.4
    // ========================================================================
    
    // Export Guardrail ID
    new cdk.CfnOutput(this, 'GuardrailId', {
      value: this.guardrail.attrGuardrailId,
      description: 'Bedrock Guardrail ID',
      exportName: exportNames.guardrailId,
    });

    // Export Guardrail Version
    new cdk.CfnOutput(this, 'GuardrailVersionOutput', {
      value: this.guardrailVersion.attrVersion,
      description: 'Bedrock Guardrail Version',
      exportName: exportNames.guardrailVersion,
    });

    // Export Guardrail ARN
    new cdk.CfnOutput(this, 'GuardrailArn', {
      value: this.guardrail.attrGuardrailArn,
      description: 'Bedrock Guardrail ARN',
      exportName: exportNames.guardrailArn,
    });
  }
}
