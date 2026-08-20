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

    IF EXISTS (
        SELECT 1 FROM accounts
         WHERE deleted_at IS NULL AND proxy_id BETWEEN 1 AND 3
    ) THEN
        RAISE EXCEPTION 'live accounts still reference legacy proxies 1..3';
    END IF;

    IF EXISTS (
        SELECT 1 FROM proxies
         WHERE deleted_at IS NULL AND backup_proxy_id BETWEEN 1 AND 3
    ) THEN
        RAISE EXCEPTION 'live proxies still use legacy proxies 1..3 as backup';
    END IF;

    IF (
        SELECT count(*) = 8
           AND bool_and(host = 'host.docker.internal')
           AND bool_and(
               (id = 1 AND protocol = 'http' AND port = 7891)
            OR (id = 2 AND protocol = 'http' AND port = 27891)
            OR (id = 3 AND protocol = 'socks5' AND port = 27892)
            OR (id = 4 AND protocol = 'http' AND port = 17901)
            OR (id = 5 AND protocol = 'http' AND port = 17902)
            OR (id = 6 AND protocol = 'http' AND port = 17903)
            OR (id = 7 AND protocol = 'http' AND port = 17904)
            OR (id = 8 AND protocol = 'http' AND port = 17905)
           )
          FROM proxies
         WHERE id BETWEEN 1 AND 8 AND deleted_at IS NULL
    ) IS NOT TRUE THEN
        RAISE EXCEPTION 'proxy 1..8 pre-cutover contract changed';
    END IF;

    UPDATE proxies SET deleted_at = clock_timestamp()
     WHERE id BETWEEN 1 AND 3 AND deleted_at IS NULL;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 3 THEN
        RAISE EXCEPTION 'expected to retire 3 legacy proxies, changed %', affected;
    END IF;

    UPDATE proxies SET host = '127.0.0.1'
     WHERE id BETWEEN 4 AND 8 AND deleted_at IS NULL;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected <> 5 THEN
        RAISE EXCEPTION 'expected to rewrite 5 slot proxies, changed %', affected;
    END IF;
END $$;

COMMIT;
