CREATE TABLE IF NOT EXISTS employees (
  id BIGINT NOT NULL PRIMARY KEY,
  employee_no VARCHAR(64) NOT NULL UNIQUE,
  name VARCHAR(128) NOT NULL,
  department VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active'
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS assets (
  id BIGINT NOT NULL PRIMARY KEY,
  asset_code VARCHAR(64) NOT NULL UNIQUE,
  name VARCHAR(128) NOT NULL,
  assigned_employee_id BIGINT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'in_use',
  CONSTRAINT fk_assets_employee FOREIGN KEY (assigned_employee_id) REFERENCES employees(id)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tickets (
  id BIGINT NOT NULL PRIMARY KEY,
  employee_id BIGINT NOT NULL,
  asset_id BIGINT NULL,
  issue TEXT NOT NULL,
  priority VARCHAR(16) NOT NULL DEFAULT 'normal',
  status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_tickets_employee FOREIGN KEY (employee_id) REFERENCES employees(id),
  CONSTRAINT fk_tickets_asset FOREIGN KEY (asset_id) REFERENCES assets(id)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

INSERT INTO employees (id, employee_no, name, department)
VALUES (10086, '10086', '张三', '研发部')
ON DUPLICATE KEY UPDATE name = VALUES(name), department = VALUES(department);

INSERT INTO assets (id, asset_code, name, assigned_employee_id)
VALUES (10086001, 'A-001', 'Dell 显示器', 10086)
ON DUPLICATE KEY UPDATE name = VALUES(name), assigned_employee_id = VALUES(assigned_employee_id);
