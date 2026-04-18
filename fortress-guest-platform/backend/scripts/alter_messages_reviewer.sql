ALTER TABLE public.messages
    ADD COLUMN IF NOT EXISTS reviewed_by UUID;

ALTER TABLE public.messages
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
