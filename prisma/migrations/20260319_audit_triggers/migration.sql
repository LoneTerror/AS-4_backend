-- =============================================================================
-- FILE: prisma/migrations/YYYYMMDDHHMMSS_audit_triggers/migration.sql
-- Run AFTER seed.py completes.
-- =============================================================================

-- 1. SYSTEM SENTINEL EMPLOYEE
DO $$
DECLARE
  v_system_id  UUID := '00000000-0000-0000-0000-000000000000';
  v_dept_id    UUID;
  v_desig_id   UUID;
  v_status_id  UUID;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM employees WHERE employee_id = v_system_id) THEN
    SELECT department_id INTO v_dept_id FROM departments WHERE department_code = 'HR' LIMIT 1;
    IF v_dept_id IS NULL THEN SELECT department_id INTO v_dept_id FROM departments LIMIT 1; END IF;
    IF v_dept_id IS NULL THEN RAISE EXCEPTION 'No departments found. Run seed.py first.'; END IF;

    SELECT designation_id INTO v_desig_id FROM designations ORDER BY level DESC LIMIT 1;
    IF v_desig_id IS NULL THEN RAISE EXCEPTION 'No designations found. Run seed.py first.'; END IF;

    -- seed.py sets entity_type='EMPLOYEE' for ACTIVE status (S_EMP_ACTIVE)
    SELECT status_id INTO v_status_id FROM status_master
     WHERE status_code = 'ACTIVE' AND entity_type = 'EMPLOYEE' LIMIT 1;
    -- fallback: any ACTIVE
    IF v_status_id IS NULL THEN
      SELECT status_id INTO v_status_id FROM status_master WHERE status_code = 'ACTIVE' LIMIT 1;
    END IF;
    IF v_status_id IS NULL THEN RAISE EXCEPTION 'No ACTIVE status found. Run seed.py first.'; END IF;

    INSERT INTO employees (
      employee_id, username, email, designation_id, password_hash,
      department_id, date_of_joining, status_id, created_at, updated_at
    ) VALUES (
      v_system_id, 'system', 'system@internal', v_desig_id,
      'NOT_A_REAL_HASH_DO_NOT_LOGIN',
      v_dept_id, CURRENT_DATE, v_status_id, NOW(), NOW()
    );
    RAISE NOTICE 'System sentinel created: %', v_system_id;
  ELSE
    RAISE NOTICE 'System sentinel already exists — skipping';
  END IF;
END $$;


-- 2. AUDIT TRIGGER FUNCTION
CREATE OR REPLACE FUNCTION fn_audit_trigger()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_sentinel   UUID   := '00000000-0000-0000-0000-000000000000';
  v_user_id    TEXT;
  v_ip         TEXT;
  v_ua         TEXT;
  v_record_id  UUID;
  v_old_json   JSONB;
  v_new_json   JSONB;
  col          TEXT;
  SENSITIVE    TEXT[] := ARRAY['password_hash', 'token_hash', 'replaced_by_token'];
BEGIN
  v_user_id := NULLIF(TRIM(current_setting('app.current_user_id', true)), '');
  v_ip      := NULLIF(TRIM(current_setting('app.client_ip',        true)), '');
  v_ua      := NULLIF(TRIM(current_setting('app.user_agent',       true)), '');
  IF v_user_id IS NULL THEN v_user_id := v_sentinel::TEXT; END IF;

  v_record_id := CASE TG_TABLE_NAME
    WHEN 'employees'          THEN COALESCE(NEW.employee_id,        OLD.employee_id)
    WHEN 'departments'        THEN COALESCE(NEW.department_id,      OLD.department_id)
    WHEN 'department_types'   THEN COALESCE(NEW.department_type_id, OLD.department_type_id)
    WHEN 'designations'       THEN COALESCE(NEW.designation_id,     OLD.designation_id)
    WHEN 'reviews'            THEN COALESCE(NEW.review_id,          OLD.review_id)
    WHEN 'review_categories'  THEN COALESCE(NEW.category_id,        OLD.category_id)
    WHEN 'reward_catalog'     THEN COALESCE(NEW.catalog_id,         OLD.catalog_id)
    WHEN 'reward_categories'  THEN COALESCE(NEW.category_id,        OLD.category_id)
    WHEN 'reward_history'     THEN COALESCE(NEW.history_id,         OLD.history_id)
    WHEN 'wallets'            THEN COALESCE(NEW.wallet_id,          OLD.wallet_id)
    WHEN 'transactions'       THEN COALESCE(NEW.transaction_id,     OLD.transaction_id)
    WHEN 'transaction_types'  THEN COALESCE(NEW.type_id,            OLD.type_id)
    WHEN 'employee_roles'     THEN COALESCE(NEW.employee_role_id,   OLD.employee_role_id)
    WHEN 'roles'              THEN COALESCE(NEW.role_id,            OLD.role_id)
    WHEN 'route_permissions'  THEN COALESCE(NEW.id,                 OLD.id)
    WHEN 'status_master'      THEN COALESCE(NEW.status_id,          OLD.status_id)
    WHEN 'refresh_tokens'     THEN COALESCE(NEW.token_id,           OLD.token_id)
    ELSE gen_random_uuid()
  END;

  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    v_old_json := to_jsonb(OLD);
    FOREACH col IN ARRAY SENSITIVE LOOP v_old_json := v_old_json - col; END LOOP;
  END IF;
  IF TG_OP IN ('INSERT', 'UPDATE') THEN
    v_new_json := to_jsonb(NEW);
    FOREACH col IN ARRAY SENSITIVE LOOP v_new_json := v_new_json - col; END LOOP;
  END IF;

  INSERT INTO audit_log (
    table_name, record_id, operation_type,
    old_values, new_values, performed_by,
    performed_at, ip_address, user_agent
  ) VALUES (
    TG_TABLE_NAME, v_record_id, TG_OP,
    v_old_json, v_new_json, v_user_id::UUID,
    NOW(), v_ip, v_ua
  );

  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
EXCEPTION WHEN OTHERS THEN
  RAISE WARNING 'fn_audit_trigger failed | table=% op=% | %', TG_TABLE_NAME, TG_OP, SQLERRM;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$;


-- 3. ATTACH TRIGGERS TO ALL 17 TABLES
DO $$ BEGIN
  DROP TRIGGER IF EXISTS trg_audit_employees         ON employees;
  CREATE TRIGGER trg_audit_employees
    AFTER INSERT OR UPDATE OR DELETE ON employees
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_departments       ON departments;
  CREATE TRIGGER trg_audit_departments
    AFTER INSERT OR UPDATE OR DELETE ON departments
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_department_types  ON department_types;
  CREATE TRIGGER trg_audit_department_types
    AFTER INSERT OR UPDATE OR DELETE ON department_types
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_designations      ON designations;
  CREATE TRIGGER trg_audit_designations
    AFTER INSERT OR UPDATE OR DELETE ON designations
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_roles             ON roles;
  CREATE TRIGGER trg_audit_roles
    AFTER INSERT OR UPDATE OR DELETE ON roles
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_employee_roles    ON employee_roles;
  CREATE TRIGGER trg_audit_employee_roles
    AFTER INSERT OR UPDATE OR DELETE ON employee_roles
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_route_permissions ON route_permissions;
  CREATE TRIGGER trg_audit_route_permissions
    AFTER INSERT OR UPDATE OR DELETE ON route_permissions
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_status_master     ON status_master;
  CREATE TRIGGER trg_audit_status_master
    AFTER INSERT OR UPDATE OR DELETE ON status_master
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_reviews           ON reviews;
  CREATE TRIGGER trg_audit_reviews
    AFTER INSERT OR UPDATE OR DELETE ON reviews
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_review_categories ON review_categories;
  CREATE TRIGGER trg_audit_review_categories
    AFTER INSERT OR UPDATE OR DELETE ON review_categories
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_reward_catalog    ON reward_catalog;
  CREATE TRIGGER trg_audit_reward_catalog
    AFTER INSERT OR UPDATE OR DELETE ON reward_catalog
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_reward_categories ON reward_categories;
  CREATE TRIGGER trg_audit_reward_categories
    AFTER INSERT OR UPDATE OR DELETE ON reward_categories
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_reward_history    ON reward_history;
  CREATE TRIGGER trg_audit_reward_history
    AFTER INSERT OR UPDATE OR DELETE ON reward_history
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_wallets           ON wallets;
  CREATE TRIGGER trg_audit_wallets
    AFTER INSERT OR UPDATE OR DELETE ON wallets
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_transactions      ON transactions;
  CREATE TRIGGER trg_audit_transactions
    AFTER INSERT OR UPDATE OR DELETE ON transactions
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_transaction_types ON transaction_types;
  CREATE TRIGGER trg_audit_transaction_types
    AFTER INSERT OR UPDATE OR DELETE ON transaction_types
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  DROP TRIGGER IF EXISTS trg_audit_refresh_tokens    ON refresh_tokens;
  CREATE TRIGGER trg_audit_refresh_tokens
    AFTER INSERT OR UPDATE OR DELETE ON refresh_tokens
    FOR EACH ROW EXECUTE FUNCTION fn_audit_trigger();

  RAISE NOTICE 'All 17 audit triggers created successfully';
END $$;


-- 4. IMMUTABILITY — app user cannot modify or delete audit records
DO $$
DECLARE app_user TEXT;
BEGIN
  app_user := NULLIF(TRIM(current_setting('app.db_user', true)), '');
  IF app_user IS NULL THEN app_user := 'rnr_app_user'; END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = app_user) THEN
    EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM %I', app_user);
    RAISE NOTICE 'Revoked UPDATE/DELETE/TRUNCATE on audit_log from %', app_user;
  ELSE
    RAISE WARNING
      'Role "%" not found — run manually: REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM <your_app_user>',
      app_user;
  END IF;
END $$;


-- 5. READ-ONLY AUDIT ROLE for compliance officers
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rnr_audit_reader') THEN
    CREATE ROLE rnr_audit_reader;
    RAISE NOTICE 'Role rnr_audit_reader created';
  END IF;
END $$;
GRANT SELECT ON audit_log TO rnr_audit_reader;


-- 6. RETENTION INDEX for 90-day archival job
-- Partial index predicates require IMMUTABLE functions — NOW() is STABLE
-- (varies per query), so a WHERE clause using it is rejected by Postgres.
-- Plain index on performed_at is sufficient; the archival job applies the
-- date filter at query time: WHERE performed_at < NOW() - INTERVAL '90 days'
CREATE INDEX IF NOT EXISTS idx_audit_log_archive_candidate
  ON audit_log (performed_at);


DO $$ BEGIN
  RAISE NOTICE 'audit_triggers migration complete — sentinel + 17 triggers + immutability';
END $$;