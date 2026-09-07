SET NAMES utf8mb4;

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
  status VARCHAR(32) NOT NULL DEFAULT 'in_use'
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS employee_assets (
  employee_id BIGINT NOT NULL,
  asset_id BIGINT NOT NULL,
  PRIMARY KEY (employee_id, asset_id),
  CONSTRAINT fk_employee_assets_employee FOREIGN KEY (employee_id) REFERENCES employees(id),
  CONSTRAINT fk_employee_assets_asset FOREIGN KEY (asset_id) REFERENCES assets(id)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tickets (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  request_id VARCHAR(64) NULL,
  employee_id BIGINT NOT NULL,
  asset_id BIGINT NOT NULL,
  issue TEXT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT uq_tickets_request_id UNIQUE (request_id),
  CONSTRAINT fk_tickets_employee FOREIGN KEY (employee_id) REFERENCES employees(id),
  CONSTRAINT fk_tickets_asset FOREIGN KEY (asset_id) REFERENCES assets(id)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

INSERT INTO employees (id, employee_no, name, department) VALUES
  (10001, '10001', '张伟', '研发部'),
  (10002, '10002', '李娜', '财务部'),
  (10003, '10003', '王强', '市场部'),
  (10004, '10004', '赵敏', '人事部'),
  (10005, '10005', '陈杰', '客服部'),
  (10006, '10006', '刘洋', '研发部'),
  (10007, '10007', '杨帆', '运维部'),
  (10008, '10008', '黄丽', '行政部'),
  (10009, '10009', '周磊', '法务部'),
  (10010, '10010', '吴婷', '采购部'),
  (10086, '10086', '张三', '研发部')
ON DUPLICATE KEY UPDATE name = VALUES(name), department = VALUES(department), status = 'active';

INSERT INTO assets (id, asset_code, name) VALUES
  (20001, 'MON-001', 'Dell 显示器'),
  (20002, 'MON-002', '联想显示器'),
  (20003, 'LAP-001', 'ThinkPad 笔记本'),
  (20004, 'LAP-002', 'Dell 笔记本'),
  (20005, 'DESK-001', 'HP 台式机'),
  (20006, 'PHONE-001', 'iPhone 工作机'),
  (20007, 'PHONE-002', '华为工作机'),
  (20008, 'PRN-001', '惠普打印机'),
  (20009, 'ROUTER-001', '企业路由器'),
  (20010, 'TABLET-001', '安卓平板')
ON DUPLICATE KEY UPDATE name = VALUES(name), status = 'in_use';

INSERT IGNORE INTO employee_assets (employee_id, asset_id) VALUES
  (10001, 20001), (10001, 20003), (10002, 20001), (10002, 20006),
  (10003, 20002), (10003, 20005), (10004, 20004), (10004, 20007),
  (10005, 20008), (10005, 20010), (10006, 20003), (10006, 20009),
  (10007, 20004), (10007, 20009), (10008, 20002), (10008, 20008),
  (10009, 20005), (10009, 20006), (10010, 20007), (10010, 20010),
  (10086, 20001), (10086, 20003);
