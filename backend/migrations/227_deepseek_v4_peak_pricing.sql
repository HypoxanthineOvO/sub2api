-- DeepSeek V4 peak/off-peak channel pricing (2026-08).
-- Existing production rows are one model per pricing row. Fail closed if that
-- invariant is not true instead of changing a row shared by other models.

DO $$
DECLARE
  v_channel_id BIGINT;
  v_model TEXT;
  v_count INTEGER;
  v_input NUMERIC;
  v_output NUMERIC;
  v_cache_read NUMERIC;
  v_time_pricing JSONB := '{"timezone":"UTC","periods":[{"start_time":"01:00","end_time":"04:00","multiplier":2},{"start_time":"06:00","end_time":"10:00","multiplier":2}]}'::jsonb;
BEGIN
  SELECT id INTO v_channel_id FROM channels WHERE name = 'Deepseek' LIMIT 1;
  IF v_channel_id IS NULL THEN
    RETURN;
  END IF;

  FOREACH v_model IN ARRAY ARRAY[
    'deepseek-v4-pro', 'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp'
  ] LOOP
    IF v_model = 'deepseek-v4-pro' THEN
      v_input := 6.6e-7; v_output := 1.98e-6; v_cache_read := 2.2e-8;
    ELSE
      v_input := 2.2e-7; v_output := 6.6e-7; v_cache_read := 7e-9;
    END IF;

    SELECT count(*) INTO v_count
    FROM channel_model_pricing
    WHERE channel_id = v_channel_id AND platform = 'deepseek'
      AND models = jsonb_build_array(v_model);
    IF v_count > 1 THEN
      RAISE EXCEPTION 'migration 227 found % duplicate pricing rows for %', v_count, v_model;
    ELSIF v_count = 1 THEN
      UPDATE channel_model_pricing
      SET input_price = v_input, output_price = v_output,
          cache_read_price = v_cache_read, billing_mode = 'token',
          time_pricing = v_time_pricing, updated_at = NOW()
      WHERE channel_id = v_channel_id AND platform = 'deepseek'
        AND models = jsonb_build_array(v_model);
    ELSE
      INSERT INTO channel_model_pricing
        (channel_id, platform, models, billing_mode, input_price, output_price, cache_read_price, time_pricing)
      VALUES
        (v_channel_id, 'deepseek', jsonb_build_array(v_model), 'token',
         v_input, v_output, v_cache_read, v_time_pricing);
    END IF;
  END LOOP;
END $$;
