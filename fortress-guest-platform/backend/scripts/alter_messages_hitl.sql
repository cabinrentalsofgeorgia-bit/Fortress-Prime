DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_type
        WHERE typname = 'message_approval_status'
    ) THEN
        CREATE TYPE message_approval_status AS ENUM (
            'pending_approval',
            'approved',
            'rejected'
        );
    END IF;
END
$$;

ALTER TABLE public.messages
    ADD COLUMN IF NOT EXISTS approval_status message_approval_status;

ALTER TABLE public.messages
    ADD COLUMN IF NOT EXISTS agent_reasoning TEXT;

UPDATE public.messages
SET approval_status = 'approved'
WHERE approval_status IS NULL;

ALTER TABLE public.messages
    ALTER COLUMN approval_status SET DEFAULT 'approved';

ALTER TABLE public.messages
    ALTER COLUMN approval_status SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_messages_approval_status
    ON public.messages (approval_status);
