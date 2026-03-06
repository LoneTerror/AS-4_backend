-- CreateTable
CREATE TABLE "audit_log" (
    "audit_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "table_name" VARCHAR(100) NOT NULL,
    "record_id" UUID NOT NULL,
    "operation_type" VARCHAR(50) NOT NULL,
    "old_values" JSONB,
    "new_values" JSONB,
    "performed_by" UUID NOT NULL,
    "performed_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "ip_address" VARCHAR(45),
    "user_agent" TEXT,

    CONSTRAINT "audit_log_pkey" PRIMARY KEY ("audit_id")
);

-- CreateTable
CREATE TABLE "department_types" (
    "department_type_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "type_name" VARCHAR(100) NOT NULL,
    "type_code" VARCHAR(50) NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID,

    CONSTRAINT "department_types_pkey" PRIMARY KEY ("department_type_id")
);

-- CreateTable
CREATE TABLE "departments" (
    "department_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "department_name" VARCHAR(100) NOT NULL,
    "department_code" VARCHAR(50) NOT NULL,
    "department_type_id" UUID NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID,

    CONSTRAINT "departments_pkey" PRIMARY KEY ("department_id")
);

-- CreateTable
CREATE TABLE "designations" (
    "designation_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "designation_name" VARCHAR(100) NOT NULL,
    "designation_code" VARCHAR(50) NOT NULL,
    "level" INTEGER NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID,

    CONSTRAINT "designations_pkey" PRIMARY KEY ("designation_id")
);

-- CreateTable
CREATE TABLE "employee_roles" (
    "employee_role_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "employee_id" UUID NOT NULL,
    "role_id" UUID NOT NULL,
    "assigned_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "assigned_by" UUID NOT NULL,
    "revoked_at" TIMESTAMPTZ(6),
    "revoked_by" UUID,
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID NOT NULL,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID NOT NULL,

    CONSTRAINT "employee_roles_pkey" PRIMARY KEY ("employee_role_id")
);

-- CreateTable
CREATE TABLE "employees" (
    "employee_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "username" VARCHAR(100) NOT NULL,
    "email" VARCHAR(255) NOT NULL,
    "designation_id" UUID NOT NULL,
    "password_hash" VARCHAR(255) NOT NULL,
    "department_id" UUID NOT NULL,
    "manager_id" UUID,
    "date_of_joining" DATE NOT NULL,
    "status_id" UUID NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID,
    "date_of_birth" DATE,

    CONSTRAINT "employees_pkey" PRIMARY KEY ("employee_id")
);

-- CreateTable
CREATE TABLE "notifications" (
    "notification_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "employee_id" UUID NOT NULL,
    "title" VARCHAR(200) NOT NULL,
    "message" TEXT NOT NULL,
    "type" VARCHAR(50) NOT NULL,
    "is_read" BOOLEAN NOT NULL DEFAULT false,
    "email_sent" BOOLEAN NOT NULL DEFAULT false,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "read_at" TIMESTAMPTZ(6),

    CONSTRAINT "notifications_pkey" PRIMARY KEY ("notification_id")
);

-- CreateTable
CREATE TABLE "points_config" (
    "config_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "config_key" VARCHAR(100) NOT NULL,
    "config_value" DECIMAL(10,6) NOT NULL,
    "description" TEXT,
    "effective_from" DATE,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID,

    CONSTRAINT "points_config_pkey" PRIMARY KEY ("config_id")
);

-- CreateTable
CREATE TABLE "refresh_tokens" (
    "token_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "token_hash" VARCHAR(255) NOT NULL,
    "employee_id" UUID NOT NULL,
    "expires_at" TIMESTAMPTZ(6) NOT NULL,
    "revoked_at" TIMESTAMPTZ(6),
    "replaced_by_token" VARCHAR(255),
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,

    CONSTRAINT "refresh_tokens_pkey" PRIMARY KEY ("token_id")
);

-- CreateTable
CREATE TABLE "review_categories" (
    "category_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "category_code" VARCHAR(50) NOT NULL,
    "category_name" VARCHAR(100) NOT NULL,
    "multiplier" DECIMAL(5,4) NOT NULL,
    "description" TEXT,
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID,

    CONSTRAINT "review_categories_pkey" PRIMARY KEY ("category_id")
);

-- CreateTable
CREATE TABLE "review_category_tags" (
    "tag_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "review_id" UUID NOT NULL,
    "category_id" UUID NOT NULL,
    "multiplier_snapshot" DECIMAL(5,4) NOT NULL,
    "category_code_snapshot" VARCHAR(50) NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "review_category_tags_pkey" PRIMARY KEY ("tag_id")
);

-- CreateTable
CREATE TABLE "reviews" (
    "review_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "reviewer_id" UUID NOT NULL,
    "receiver_id" UUID NOT NULL,
    "rating" INTEGER NOT NULL,
    "comment" TEXT NOT NULL,
    "image_url" VARCHAR(500),
    "video_url" VARCHAR(500),
    "status_id" UUID NOT NULL,
    "review_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID NOT NULL,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID NOT NULL,
    "raw_points" DOUBLE PRECISION,

    CONSTRAINT "reviews_pkey" PRIMARY KEY ("review_id")
);

-- CreateTable
CREATE TABLE "reward_catalog" (
    "catalog_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "reward_name" VARCHAR(200) NOT NULL,
    "reward_code" VARCHAR(50) NOT NULL,
    "description" TEXT,
    "default_points" INTEGER NOT NULL,
    "category_id" UUID NOT NULL,
    "min_points" INTEGER NOT NULL,
    "max_points" INTEGER NOT NULL,
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "available_stock" INTEGER NOT NULL DEFAULT 0,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID,

    CONSTRAINT "reward_catalog_pkey" PRIMARY KEY ("catalog_id")
);

-- CreateTable
CREATE TABLE "reward_categories" (
    "category_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "category_name" VARCHAR(100) NOT NULL,
    "category_code" VARCHAR(50) NOT NULL,
    "description" TEXT,
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID,

    CONSTRAINT "reward_categories_pkey" PRIMARY KEY ("category_id")
);

-- CreateTable
CREATE TABLE "reward_history" (
    "history_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "wallet_id" UUID NOT NULL,
    "catalog_id" UUID NOT NULL,
    "granted_by" UUID NOT NULL,
    "points" INTEGER NOT NULL,
    "comment" TEXT,
    "granted_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID NOT NULL,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID NOT NULL,

    CONSTRAINT "reward_history_pkey" PRIMARY KEY ("history_id")
);

-- CreateTable
CREATE TABLE "roles" (
    "role_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "role_name" VARCHAR(100) NOT NULL,
    "role_code" VARCHAR(50) NOT NULL,
    "description" TEXT,
    "reviewer_weight" DECIMAL(5,4) NOT NULL DEFAULT 1.0000,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID,

    CONSTRAINT "roles_pkey" PRIMARY KEY ("role_id")
);

-- CreateTable
CREATE TABLE "seasonal_multipliers" (
    "seasonal_multiplier_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "quarter" INTEGER NOT NULL,
    "label" VARCHAR(50) NOT NULL,
    "multiplier" DECIMAL(5,4) NOT NULL,
    "effective_from" DATE,
    "effective_to" DATE,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID,

    CONSTRAINT "seasonal_multipliers_pkey" PRIMARY KEY ("seasonal_multiplier_id")
);

-- CreateTable
CREATE TABLE "status_master" (
    "status_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "status_code" VARCHAR(50) NOT NULL,
    "status_name" VARCHAR(100) NOT NULL,
    "description" TEXT,
    "entity_type" VARCHAR(50) NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID,

    CONSTRAINT "status_master_pkey" PRIMARY KEY ("status_id")
);

-- CreateTable
CREATE TABLE "transaction_types" (
    "type_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "type_name" VARCHAR(100) NOT NULL,
    "type_code" VARCHAR(50) NOT NULL,
    "description" TEXT,
    "is_credit" BOOLEAN NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID,

    CONSTRAINT "transaction_types_pkey" PRIMARY KEY ("type_id")
);

-- CreateTable
CREATE TABLE "transactions" (
    "transaction_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "wallet_id" UUID NOT NULL,
    "amount" INTEGER NOT NULL,
    "transaction_type_id" UUID NOT NULL,
    "status_id" UUID NOT NULL,
    "description" TEXT,
    "reference_number" VARCHAR(100) NOT NULL,
    "transaction_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID NOT NULL,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID NOT NULL,

    CONSTRAINT "transactions_pkey" PRIMARY KEY ("transaction_id")
);

-- CreateTable
CREATE TABLE "wallets" (
    "wallet_id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "employee_id" UUID NOT NULL,
    "available_points" INTEGER NOT NULL DEFAULT 0,
    "redeemed_points" INTEGER NOT NULL DEFAULT 0,
    "total_earned_points" INTEGER NOT NULL DEFAULT 0,
    "version" INTEGER NOT NULL DEFAULT 1,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID NOT NULL,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    "updated_by" UUID NOT NULL,

    CONSTRAINT "wallets_pkey" PRIMARY KEY ("wallet_id")
);

-- CreateTable
CREATE TABLE "route_permissions" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "route_key" VARCHAR(200) NOT NULL,
    "role_id" UUID NOT NULL,
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_by" UUID,
    "updated_at" TIMESTAMPTZ(6),
    "updated_by" UUID,

    CONSTRAINT "route_permissions_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "audit_log_operation_type_idx" ON "audit_log"("operation_type");

-- CreateIndex
CREATE INDEX "audit_log_performed_at_idx" ON "audit_log"("performed_at");

-- CreateIndex
CREATE INDEX "audit_log_performed_by_idx" ON "audit_log"("performed_by");

-- CreateIndex
CREATE INDEX "audit_log_record_id_idx" ON "audit_log"("record_id");

-- CreateIndex
CREATE INDEX "audit_log_table_name_idx" ON "audit_log"("table_name");

-- CreateIndex
CREATE INDEX "audit_log_table_name_record_id_idx" ON "audit_log"("table_name", "record_id");

-- CreateIndex
CREATE INDEX "audit_log_table_name_record_id_performed_at_idx" ON "audit_log"("table_name", "record_id", "performed_at");

-- CreateIndex
CREATE UNIQUE INDEX "department_types_type_name_key" ON "department_types"("type_name");

-- CreateIndex
CREATE UNIQUE INDEX "department_types_type_code_key" ON "department_types"("type_code");

-- CreateIndex
CREATE UNIQUE INDEX "departments_department_name_key" ON "departments"("department_name");

-- CreateIndex
CREATE UNIQUE INDEX "departments_department_code_key" ON "departments"("department_code");

-- CreateIndex
CREATE INDEX "departments_department_type_id_idx" ON "departments"("department_type_id");

-- CreateIndex
CREATE UNIQUE INDEX "designations_designation_name_key" ON "designations"("designation_name");

-- CreateIndex
CREATE UNIQUE INDEX "designations_designation_code_key" ON "designations"("designation_code");

-- CreateIndex
CREATE INDEX "designations_level_idx" ON "designations"("level");

-- CreateIndex
CREATE INDEX "employee_roles_assigned_at_idx" ON "employee_roles"("assigned_at");

-- CreateIndex
CREATE INDEX "employee_roles_employee_id_idx" ON "employee_roles"("employee_id");

-- CreateIndex
CREATE INDEX "employee_roles_employee_id_is_active_idx" ON "employee_roles"("employee_id", "is_active");

-- CreateIndex
CREATE INDEX "employee_roles_is_active_idx" ON "employee_roles"("is_active");

-- CreateIndex
CREATE INDEX "employee_roles_revoked_at_idx" ON "employee_roles"("revoked_at");

-- CreateIndex
CREATE INDEX "employee_roles_role_id_idx" ON "employee_roles"("role_id");

-- CreateIndex
CREATE UNIQUE INDEX "employee_roles_employee_id_role_id_is_active_key" ON "employee_roles"("employee_id", "role_id", "is_active");

-- CreateIndex
CREATE UNIQUE INDEX "employees_username_key" ON "employees"("username");

-- CreateIndex
CREATE UNIQUE INDEX "employees_email_key" ON "employees"("email");

-- CreateIndex
CREATE INDEX "employees_created_at_idx" ON "employees"("created_at");

-- CreateIndex
CREATE INDEX "employees_date_of_birth_idx" ON "employees"("date_of_birth");

-- CreateIndex
CREATE INDEX "employees_date_of_joining_idx" ON "employees"("date_of_joining");

-- CreateIndex
CREATE INDEX "employees_department_id_idx" ON "employees"("department_id");

-- CreateIndex
CREATE INDEX "employees_department_id_status_id_idx" ON "employees"("department_id", "status_id");

-- CreateIndex
CREATE INDEX "employees_designation_id_idx" ON "employees"("designation_id");

-- CreateIndex
CREATE INDEX "employees_manager_id_idx" ON "employees"("manager_id");

-- CreateIndex
CREATE INDEX "employees_manager_id_status_id_idx" ON "employees"("manager_id", "status_id");

-- CreateIndex
CREATE INDEX "employees_status_id_idx" ON "employees"("status_id");

-- CreateIndex
CREATE INDEX "notifications_created_at_idx" ON "notifications"("created_at");

-- CreateIndex
CREATE INDEX "notifications_email_sent_idx" ON "notifications"("email_sent");

-- CreateIndex
CREATE INDEX "notifications_employee_id_idx" ON "notifications"("employee_id");

-- CreateIndex
CREATE INDEX "notifications_employee_id_is_read_idx" ON "notifications"("employee_id", "is_read");

-- CreateIndex
CREATE UNIQUE INDEX "points_config_config_key_key" ON "points_config"("config_key");

-- CreateIndex
CREATE INDEX "points_config_config_key_idx" ON "points_config"("config_key");

-- CreateIndex
CREATE UNIQUE INDEX "refresh_tokens_token_hash_key" ON "refresh_tokens"("token_hash");

-- CreateIndex
CREATE INDEX "refresh_tokens_employee_id_idx" ON "refresh_tokens"("employee_id");

-- CreateIndex
CREATE INDEX "refresh_tokens_token_hash_idx" ON "refresh_tokens"("token_hash");

-- CreateIndex
CREATE UNIQUE INDEX "review_categories_category_code_key" ON "review_categories"("category_code");

-- CreateIndex
CREATE UNIQUE INDEX "review_categories_category_name_key" ON "review_categories"("category_name");

-- CreateIndex
CREATE INDEX "review_categories_category_code_idx" ON "review_categories"("category_code");

-- CreateIndex
CREATE INDEX "review_categories_is_active_idx" ON "review_categories"("is_active");

-- CreateIndex
CREATE INDEX "review_category_tags_review_id_idx" ON "review_category_tags"("review_id");

-- CreateIndex
CREATE INDEX "review_category_tags_category_id_idx" ON "review_category_tags"("category_id");

-- CreateIndex
CREATE UNIQUE INDEX "review_category_tags_review_id_category_id_key" ON "review_category_tags"("review_id", "category_id");

-- CreateIndex
CREATE INDEX "reviews_rating_idx" ON "reviews"("rating");

-- CreateIndex
CREATE INDEX "reviews_receiver_id_idx" ON "reviews"("receiver_id");

-- CreateIndex
CREATE INDEX "reviews_receiver_id_raw_points_idx" ON "reviews"("receiver_id", "raw_points");

-- CreateIndex
CREATE INDEX "reviews_receiver_id_review_at_idx" ON "reviews"("receiver_id", "review_at");

-- CreateIndex
CREATE INDEX "reviews_receiver_id_status_id_idx" ON "reviews"("receiver_id", "status_id");

-- CreateIndex
CREATE INDEX "reviews_review_at_idx" ON "reviews"("review_at");

-- CreateIndex
CREATE INDEX "reviews_reviewer_id_idx" ON "reviews"("reviewer_id");

-- CreateIndex
CREATE INDEX "reviews_reviewer_id_review_at_idx" ON "reviews"("reviewer_id", "review_at");

-- CreateIndex
CREATE INDEX "reviews_status_id_idx" ON "reviews"("status_id");

-- CreateIndex
CREATE UNIQUE INDEX "reward_catalog_reward_name_key" ON "reward_catalog"("reward_name");

-- CreateIndex
CREATE UNIQUE INDEX "reward_catalog_reward_code_key" ON "reward_catalog"("reward_code");

-- CreateIndex
CREATE INDEX "reward_catalog_category_id_idx" ON "reward_catalog"("category_id");

-- CreateIndex
CREATE INDEX "reward_catalog_category_id_is_active_idx" ON "reward_catalog"("category_id", "is_active");

-- CreateIndex
CREATE INDEX "reward_catalog_is_active_idx" ON "reward_catalog"("is_active");

-- CreateIndex
CREATE INDEX "reward_catalog_min_points_max_points_idx" ON "reward_catalog"("min_points", "max_points");

-- CreateIndex
CREATE UNIQUE INDEX "reward_categories_category_name_key" ON "reward_categories"("category_name");

-- CreateIndex
CREATE UNIQUE INDEX "reward_categories_category_code_key" ON "reward_categories"("category_code");

-- CreateIndex
CREATE INDEX "reward_categories_is_active_idx" ON "reward_categories"("is_active");

-- CreateIndex
CREATE INDEX "reward_history_catalog_id_granted_at_idx" ON "reward_history"("catalog_id", "granted_at");

-- CreateIndex
CREATE INDEX "reward_history_catalog_id_idx" ON "reward_history"("catalog_id");

-- CreateIndex
CREATE INDEX "reward_history_granted_at_idx" ON "reward_history"("granted_at");

-- CreateIndex
CREATE INDEX "reward_history_granted_by_idx" ON "reward_history"("granted_by");

-- CreateIndex
CREATE INDEX "reward_history_wallet_id_granted_at_idx" ON "reward_history"("wallet_id", "granted_at");

-- CreateIndex
CREATE INDEX "reward_history_wallet_id_idx" ON "reward_history"("wallet_id");

-- CreateIndex
CREATE UNIQUE INDEX "roles_role_name_key" ON "roles"("role_name");

-- CreateIndex
CREATE UNIQUE INDEX "roles_role_code_key" ON "roles"("role_code");

-- CreateIndex
CREATE INDEX "seasonal_multipliers_effective_from_idx" ON "seasonal_multipliers"("effective_from");

-- CreateIndex
CREATE INDEX "seasonal_multipliers_quarter_idx" ON "seasonal_multipliers"("quarter");

-- CreateIndex
CREATE UNIQUE INDEX "seasonal_multipliers_quarter_effective_from_key" ON "seasonal_multipliers"("quarter", "effective_from");

-- CreateIndex
CREATE UNIQUE INDEX "status_master_status_code_key" ON "status_master"("status_code");

-- CreateIndex
CREATE INDEX "status_master_entity_type_idx" ON "status_master"("entity_type");

-- CreateIndex
CREATE INDEX "status_master_entity_type_status_code_idx" ON "status_master"("entity_type", "status_code");

-- CreateIndex
CREATE UNIQUE INDEX "transaction_types_type_name_key" ON "transaction_types"("type_name");

-- CreateIndex
CREATE UNIQUE INDEX "transaction_types_type_code_key" ON "transaction_types"("type_code");

-- CreateIndex
CREATE INDEX "transaction_types_is_credit_idx" ON "transaction_types"("is_credit");

-- CreateIndex
CREATE UNIQUE INDEX "transactions_reference_number_key" ON "transactions"("reference_number");

-- CreateIndex
CREATE INDEX "transactions_created_at_idx" ON "transactions"("created_at");

-- CreateIndex
CREATE INDEX "transactions_status_id_idx" ON "transactions"("status_id");

-- CreateIndex
CREATE INDEX "transactions_transaction_at_idx" ON "transactions"("transaction_at");

-- CreateIndex
CREATE INDEX "transactions_transaction_type_id_idx" ON "transactions"("transaction_type_id");

-- CreateIndex
CREATE INDEX "transactions_wallet_id_idx" ON "transactions"("wallet_id");

-- CreateIndex
CREATE INDEX "transactions_wallet_id_status_id_idx" ON "transactions"("wallet_id", "status_id");

-- CreateIndex
CREATE INDEX "transactions_wallet_id_transaction_at_idx" ON "transactions"("wallet_id", "transaction_at");

-- CreateIndex
CREATE UNIQUE INDEX "wallets_employee_id_key" ON "wallets"("employee_id");

-- CreateIndex
CREATE INDEX "wallets_available_points_idx" ON "wallets"("available_points");

-- CreateIndex
CREATE INDEX "wallets_total_earned_points_idx" ON "wallets"("total_earned_points");

-- CreateIndex
CREATE INDEX "idx_route_permissions_route_key" ON "route_permissions"("route_key");

-- CreateIndex
CREATE UNIQUE INDEX "uq_route_permissions_route_role" ON "route_permissions"("route_key", "role_id");

-- AddForeignKey
ALTER TABLE "audit_log" ADD CONSTRAINT "audit_log_performed_by_fkey" FOREIGN KEY ("performed_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "department_types" ADD CONSTRAINT "department_types_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "department_types" ADD CONSTRAINT "department_types_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "departments" ADD CONSTRAINT "departments_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "departments" ADD CONSTRAINT "departments_department_type_id_fkey" FOREIGN KEY ("department_type_id") REFERENCES "department_types"("department_type_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "departments" ADD CONSTRAINT "departments_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "designations" ADD CONSTRAINT "designations_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "designations" ADD CONSTRAINT "designations_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee_roles" ADD CONSTRAINT "employee_roles_assigned_by_fkey" FOREIGN KEY ("assigned_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee_roles" ADD CONSTRAINT "employee_roles_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee_roles" ADD CONSTRAINT "employee_roles_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "employees"("employee_id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee_roles" ADD CONSTRAINT "employee_roles_revoked_by_fkey" FOREIGN KEY ("revoked_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee_roles" ADD CONSTRAINT "employee_roles_role_id_fkey" FOREIGN KEY ("role_id") REFERENCES "roles"("role_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee_roles" ADD CONSTRAINT "employee_roles_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employees" ADD CONSTRAINT "employees_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employees" ADD CONSTRAINT "employees_department_id_fkey" FOREIGN KEY ("department_id") REFERENCES "departments"("department_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employees" ADD CONSTRAINT "employees_designation_id_fkey" FOREIGN KEY ("designation_id") REFERENCES "designations"("designation_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employees" ADD CONSTRAINT "employees_manager_id_fkey" FOREIGN KEY ("manager_id") REFERENCES "employees"("employee_id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employees" ADD CONSTRAINT "employees_status_id_fkey" FOREIGN KEY ("status_id") REFERENCES "status_master"("status_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employees" ADD CONSTRAINT "employees_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "points_config" ADD CONSTRAINT "points_config_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "points_config" ADD CONSTRAINT "points_config_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "refresh_tokens" ADD CONSTRAINT "refresh_tokens_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "employees"("employee_id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "review_categories" ADD CONSTRAINT "review_categories_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "review_categories" ADD CONSTRAINT "review_categories_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "review_category_tags" ADD CONSTRAINT "review_category_tags_category_id_fkey" FOREIGN KEY ("category_id") REFERENCES "review_categories"("category_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "review_category_tags" ADD CONSTRAINT "review_category_tags_review_id_fkey" FOREIGN KEY ("review_id") REFERENCES "reviews"("review_id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reviews" ADD CONSTRAINT "reviews_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reviews" ADD CONSTRAINT "reviews_receiver_id_fkey" FOREIGN KEY ("receiver_id") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reviews" ADD CONSTRAINT "reviews_reviewer_id_fkey" FOREIGN KEY ("reviewer_id") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reviews" ADD CONSTRAINT "reviews_status_id_fkey" FOREIGN KEY ("status_id") REFERENCES "status_master"("status_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reviews" ADD CONSTRAINT "reviews_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reward_catalog" ADD CONSTRAINT "reward_catalog_category_id_fkey" FOREIGN KEY ("category_id") REFERENCES "reward_categories"("category_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reward_catalog" ADD CONSTRAINT "reward_catalog_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reward_catalog" ADD CONSTRAINT "reward_catalog_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reward_categories" ADD CONSTRAINT "reward_categories_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reward_categories" ADD CONSTRAINT "reward_categories_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reward_history" ADD CONSTRAINT "reward_history_catalog_id_fkey" FOREIGN KEY ("catalog_id") REFERENCES "reward_catalog"("catalog_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reward_history" ADD CONSTRAINT "reward_history_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reward_history" ADD CONSTRAINT "reward_history_granted_by_fkey" FOREIGN KEY ("granted_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reward_history" ADD CONSTRAINT "reward_history_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reward_history" ADD CONSTRAINT "reward_history_wallet_id_fkey" FOREIGN KEY ("wallet_id") REFERENCES "wallets"("wallet_id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "roles" ADD CONSTRAINT "roles_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "roles" ADD CONSTRAINT "roles_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "seasonal_multipliers" ADD CONSTRAINT "seasonal_multipliers_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "seasonal_multipliers" ADD CONSTRAINT "seasonal_multipliers_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "status_master" ADD CONSTRAINT "status_master_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "status_master" ADD CONSTRAINT "status_master_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "transaction_types" ADD CONSTRAINT "transaction_types_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "transaction_types" ADD CONSTRAINT "transaction_types_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "transactions" ADD CONSTRAINT "transactions_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "transactions" ADD CONSTRAINT "transactions_status_id_fkey" FOREIGN KEY ("status_id") REFERENCES "status_master"("status_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "transactions" ADD CONSTRAINT "transactions_transaction_type_id_fkey" FOREIGN KEY ("transaction_type_id") REFERENCES "transaction_types"("type_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "transactions" ADD CONSTRAINT "transactions_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "transactions" ADD CONSTRAINT "transactions_wallet_id_fkey" FOREIGN KEY ("wallet_id") REFERENCES "wallets"("wallet_id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "wallets" ADD CONSTRAINT "wallets_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "wallets" ADD CONSTRAINT "wallets_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "employees"("employee_id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "wallets" ADD CONSTRAINT "wallets_updated_by_fkey" FOREIGN KEY ("updated_by") REFERENCES "employees"("employee_id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "route_permissions" ADD CONSTRAINT "fk_route_permissions_role" FOREIGN KEY ("role_id") REFERENCES "roles"("role_id") ON DELETE CASCADE ON UPDATE NO ACTION;
