-- 该脚本由 Compose 的 mysql-migrate 服务在每次启动时执行，兼容已有数据卷。
ALTER TABLE tickets MODIFY COLUMN id BIGINT NOT NULL AUTO_INCREMENT;

SET @request_id_column_exists = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'tickets'
    AND COLUMN_NAME = 'request_id'
);
SET @add_request_id_column = IF(
  @request_id_column_exists = 0,
  'ALTER TABLE tickets ADD COLUMN request_id VARCHAR(64) NULL AFTER id',
  'SELECT 1'
);
PREPARE add_request_id_column_stmt FROM @add_request_id_column;
EXECUTE add_request_id_column_stmt;
DEALLOCATE PREPARE add_request_id_column_stmt;

SET @request_id_index_exists = (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'tickets'
    AND INDEX_NAME = 'uq_tickets_request_id'
);
SET @add_request_id_index = IF(
  @request_id_index_exists = 0,
  'ALTER TABLE tickets ADD UNIQUE INDEX uq_tickets_request_id (request_id)',
  'SELECT 1'
);
PREPARE add_request_id_index_stmt FROM @add_request_id_index;
EXECUTE add_request_id_index_stmt;
DEALLOCATE PREPARE add_request_id_index_stmt;
