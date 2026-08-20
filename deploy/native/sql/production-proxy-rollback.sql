\set ON_ERROR_STOP on

BEGIN;
SET LOCAL lock_timeout = '5s';
LOCK TABLE accounts IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE proxies IN SHARE ROW EXCLUSIVE MODE;

DO $$
DECLARE
    affected integer;
    live_mapping jsonb;
BEGIN
    SELECT jsonb_agg(jsonb_build_array(id, proxy_id) ORDER BY id)
      INTO live_mapping
      FROM accounts
     WHERE deleted_at IS NULL
       AND proxy_id IS NOT NULL;

    IF live_mapping IS DISTINCT FROM '[[22, 4], [36, 5], [40, 7], [41, 8]]'::jsonb THEN
        RAISE EXCEPTION 'unexpected live account/proxy mapping: %', live_mapping;
    END IF;

    IF (
        SELECT count(*) = 3
           AND bool_and(deleted_at IS NOT NULL)
          FROM proxies
         WHERE id BETWEEN 1 AND 3
    ) IS NOT TRUE THEN
        RAISE EXCEPTION 'legacy proxy rollback contract changed';
    END IF;

    IF (
        SELECT count(*) = 5
           AND bool_and(deleted_at IS NULL)
           AND bool_and(host = '127.0.0.1')
           AND bool_and(port = 17897 + id)
           AND bool_and(protocol = 'http')
          FROM proxies
         WHERE id BETWEEN 4 AND 8
    ) IS NOT TRUE THEN
        RAISE EXCEPTION 'slot proxy rollback contract changed';
    END IF;

    UPDATE proxies SET deleted_at = NULL
     WHERE id BETWEEN 1 AND 3 AND deleted_at IS NOT NULL;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 3 THEN
        RAISE EXCEPTION 'expected to restore 3 legacy proxies, changed %', affected;
    END IF;

    UPDATE proxies SET host = 'host.docker.internal'
     WHERE id BETWEEN 4 AND 8 AND deleted_at IS NULL;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 5 THEN
        RAISE EXCEPTION 'expected to restore 5 slot proxies, changed %', affected;
    END IF;
END $$;

COMMIT;
