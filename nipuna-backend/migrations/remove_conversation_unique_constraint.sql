-- Migration: Remove unique constraint on conversations table
-- This allows users to have multiple conversations with the same agent
-- Date: 2026-01-26
-- Author: System Audit

-- Drop the unique constraint
ALTER TABLE conversations DROP CONSTRAINT IF EXISTS uq_conversations_org_agent_user;

-- Add indexes for performance (optional but recommended)
CREATE INDEX IF NOT EXISTS idx_conversations_org_agent_user ON conversations(org_id, agent_id, user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_created_at ON conversations(created_at DESC);
