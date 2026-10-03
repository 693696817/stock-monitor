-- ============================================================
-- A股棱镜 · 价值投资分析系统 — MySQL 生产库结构
-- 数据库：aistock
-- 字符集：utf8mb4 / InnoDB（支持中文 + emoji，事务安全）
-- 说明：本文件为「建表 + 索引 + 外键」的唯一权威来源，
--       db.py 的 init_db() 会读取本文件并逐条执行。
-- ============================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ------------------------------------------------------------
-- 1) 用户表 users
--    存储账户核心信息、密码哈希、会员当前状态、邀请关系。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `users` (
  `id`                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `email`              VARCHAR(191)    NOT NULL                COMMENT '登录邮箱（唯一，小写存储）；纯手机号注册的账号此处为占位值 p<手机号>@phone.local（见 auth.PHONE_EMAIL_SUFFIX）',
  `username`           VARCHAR(64)     DEFAULT NULL            COMMENT '用户名/账号名',
  `password_hash`      CHAR(64)        NOT NULL                COMMENT 'pbkdf2_sha256 hex（64位）',
  `salt`               CHAR(32)        NOT NULL                COMMENT '随机盐 hex（32位）',
  `nickname`           VARCHAR(64)     DEFAULT NULL            COMMENT '昵称',
  `avatar`             VARCHAR(255)    DEFAULT NULL            COMMENT '头像URL',
  `status`             TINYINT         NOT NULL DEFAULT 1      COMMENT '1=正常 0=禁用',
  `email_verified`     TINYINT         NOT NULL DEFAULT 0      COMMENT '邮箱是否已验证',
  `phone`              VARCHAR(32)     DEFAULT NULL            COMMENT '手机号（08-31 起即登录账号，唯一；NULL 允许多个，后台手动建号可不填）',
  `phone_verified`     TINYINT         NOT NULL DEFAULT 0      COMMENT '手机是否已验证',
  `membership_level`   TINYINT         NOT NULL DEFAULT 0      COMMENT '当前会员等级 0免费 1VIP1 2VIP2',
  `membership_expiry`  DATE            DEFAULT NULL            COMMENT '会员有效期（NULL=终身）',
  `bonus_normal`       INT             NOT NULL DEFAULT 0      COMMENT '注册赠送/活动的普通分析余量（一次性，不按日重置）',
  `bonus_deep`         INT             NOT NULL DEFAULT 0      COMMENT '注册赠送/活动的深度分析余量（一次性）',
  `points`             INT             NOT NULL DEFAULT 0      COMMENT '积分',
  `invite_code`        VARCHAR(16)     DEFAULT NULL            COMMENT '本人邀请码（唯一）',
  `invited_by`         BIGINT UNSIGNED DEFAULT NULL            COMMENT '邀请人 user.id（外键软引用）',
  `last_login_at`      DATETIME        DEFAULT NULL            COMMENT '最近登录时间',
  `last_login_ip`      VARCHAR(64)     DEFAULT NULL            COMMENT '最近登录IP',
  `daily_analysis_date` DATE           DEFAULT NULL            COMMENT '每日配额计数日期（兼容旧逻辑）',
  `daily_analysis_count` INT           NOT NULL DEFAULT 0      COMMENT '每日分析计数（兼容旧逻辑）',
  `created_at`         DATETIME        NOT NULL                COMMENT '注册时间',
  `updated_at`         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_email` (`email`),
  UNIQUE KEY `uq_invite_code` (`invite_code`),
  -- 手机号唯一：纯手机号注册后 phone 就是账号，并发注册不能出现两个同号账号。
  -- MySQL 唯一索引允许多个 NULL，后台手动建号不填手机号不受影响。
  UNIQUE KEY `uq_phone` (`phone`),
  KEY `idx_invited_by` (`invited_by`),
  KEY `idx_membership` (`membership_level`, `membership_expiry`),
  KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户账户表';

-- ------------------------------------------------------------
-- 2) 会员订单表 membership_orders
--    每一笔会员开通/续费都是一条订单，支持后续真实支付对账。
--    用户当前会员状态仍以 users.membership_level/expiry 为准（冗余加速读）。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `membership_orders` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`         BIGINT UNSIGNED NOT NULL,
  `order_no`        VARCHAR(64)     NOT NULL                COMMENT '内部订单号（唯一）',
  `plan_code`       VARCHAR(32)     NOT NULL                COMMENT '套餐码 vip1/vip2',
  `level`           TINYINT         NOT NULL                COMMENT '开通等级 1/2',
  `amount`          DECIMAL(10,2)   NOT NULL DEFAULT 0.00   COMMENT '实付金额',
  `currency`        VARCHAR(8)      NOT NULL DEFAULT 'CNY',
  `payment_method`  VARCHAR(32)     DEFAULT NULL            COMMENT 'wechat/alipay/card',
  `payment_status`  TINYINT         NOT NULL DEFAULT 0      COMMENT '0待支付 1已支付 2已退款 3已关闭',
  `paid_at`         DATETIME        DEFAULT NULL,
  `start_at`        DATETIME        DEFAULT NULL            COMMENT '会员生效时间',
  `end_at`          DATETIME        DEFAULT NULL            COMMENT '会员到期时间',
  `days`            INT             NOT NULL DEFAULT 0      COMMENT '开通天数',
  `remark`          VARCHAR(255)    DEFAULT NULL            COMMENT '备注（如 演示开通）',
  `created_at`      DATETIME        NOT NULL,
  `updated_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_order_no` (`order_no`),
  KEY `idx_user` (`user_id`),
  KEY `idx_status` (`payment_status`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会员订单表';

-- ------------------------------------------------------------
-- 3) 分析记录表 analysis_records（原 analysis_log）
--    保留每次 AI 研报分析的痕迹，便于用量统计、质检与复盘。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `analysis_records` (
  `id`           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`      BIGINT UNSIGNED NOT NULL,
  `stock_name`   VARCHAR(64)     DEFAULT NULL            COMMENT '股票名称',
  `stock_code`   VARCHAR(32)     DEFAULT NULL            COMMENT '股票代码',
  `mode`         VARCHAR(16)     NOT NULL DEFAULT 'normal' COMMENT 'normal/deep',
  `model_id`     VARCHAR(32)     DEFAULT NULL            COMMENT '使用的模型渠道ID',
  `preference`   VARCHAR(32)     DEFAULT NULL            COMMENT '投资偏好ID',
  `quota_source` VARCHAR(16)     NOT NULL DEFAULT 'daily' COMMENT 'daily=计入每日/每月额度 / bonus=消耗一次性赠送，不计入',
  `report_md`    MEDIUMTEXT      DEFAULT NULL            COMMENT '生成的研报（markdown）',
  `token_usage`  INT             DEFAULT NULL            COMMENT '本次消耗 token',
  `duration_ms`  INT             DEFAULT NULL            COMMENT '耗时毫秒',
  `ip`           VARCHAR(64)     DEFAULT NULL            COMMENT '请求IP',
  `created_at`   DATETIME        NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_user_created` (`user_id`, `created_at`),
  KEY `idx_created` (`created_at`),
  KEY `idx_mode` (`mode`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI分析记录表';

-- ------------------------------------------------------------
-- 4) 邀请记录表 invite_records
--    记录「谁邀请谁 + 奖励发放」，作为邀请关系的审计轨迹。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `invite_records` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `inviter_id`    BIGINT UNSIGNED NOT NULL                COMMENT '邀请人',
  `invitee_id`    BIGINT UNSIGNED NOT NULL                COMMENT '被邀请人',
  `invite_code`   VARCHAR(16)     NOT NULL,
  `reward_days`   INT             NOT NULL DEFAULT 0      COMMENT '发放奖励天数',
  `reward_level`  TINYINT         NOT NULL DEFAULT 1      COMMENT '发放奖励等级',
  `created_at`    DATETIME        NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_invitee` (`invitee_id`),
  KEY `idx_inviter` (`inviter_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='邀请奖励记录表';

-- ------------------------------------------------------------
-- 5) 反馈表 feedback（原内存数组 FEEDBACK_DB，改为持久化）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `feedback` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    BIGINT UNSIGNED DEFAULT NULL,
  `title`      VARCHAR(255)    DEFAULT NULL            COMMENT '标题',
  `content`    TEXT            DEFAULT NULL            COMMENT '反馈内容',
  `contact`    VARCHAR(128)    DEFAULT NULL            COMMENT '联系方式',
  `votes`      INT             NOT NULL DEFAULT 0      COMMENT '赞同数',
  `status`     TINYINT         NOT NULL DEFAULT 0      COMMENT '0待审 1已采纳 2已拒绝',
  `created_at` DATETIME        NOT NULL,
  `updated_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_votes` (`votes`),
  KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户反馈表';

-- ------------------------------------------------------------
-- 6) 登录日志表 login_logs（安全审计）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `login_logs` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    BIGINT UNSIGNED DEFAULT NULL,
  `email`      VARCHAR(191)    DEFAULT NULL,
  `success`    TINYINT         NOT NULL DEFAULT 0      COMMENT '1成功 0失败',
  `ip`         VARCHAR(64)     DEFAULT NULL,
  `user_agent` VARCHAR(512)    DEFAULT NULL,
  `reason`     VARCHAR(64)     DEFAULT NULL            COMMENT '失败原因',
  `created_at` DATETIME        NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_user` (`user_id`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='登录日志表';

-- ------------------------------------------------------------
-- 7) 支付订单表 payment_orders（预留：微信/支付宝支付）
--    与 membership_orders 解耦：本表负责「收款流水」，
--    membership_orders 负责「权益发放」。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `payment_orders` (
  `id`           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`      BIGINT UNSIGNED NOT NULL,
  `order_no`     VARCHAR(64)     NOT NULL                COMMENT '商户订单号（唯一）',
  `subject`      VARCHAR(255)    NOT NULL                COMMENT '商品标题',
  `amount`       DECIMAL(10,2)   NOT NULL                COMMENT '金额',
  `currency`     VARCHAR(8)      NOT NULL DEFAULT 'CNY',
  `channel`      VARCHAR(32)     NOT NULL DEFAULT 'wechat' COMMENT 'wechat/alipay',
  `trade_no`     VARCHAR(64)     DEFAULT NULL            COMMENT '第三方交易号',
  `status`       TINYINT         NOT NULL DEFAULT 0      COMMENT '0待支付 1成功 2失败 3关闭 4退款',
  `qr_code`      TEXT            DEFAULT NULL            COMMENT '支付二维码/链接',
  `paid_at`      DATETIME        DEFAULT NULL,
  `expired_at`   DATETIME        DEFAULT NULL,
  `created_at`   DATETIME        NOT NULL,
  `updated_at`   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_order_no` (`order_no`),
  KEY `idx_user` (`user_id`),
  KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='支付流水表';

-- ------------------------------------------------------------
-- 8) 系统设置表 system_settings（后台可配置：数据源 / AI模型 / API Key）
--    键由 settings.py 的 SETTING_KEYS 管理，后台修改即时落库并热生效。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `system_settings` (
  `key`        VARCHAR(64)     NOT NULL                COMMENT '设置键',
  -- MEDIUMTEXT：接口能力目录（DATAHUB/LIXINGER）JSON 可达 7 万+ 字节，TEXT 的 65535 字节不够
  `value`      MEDIUMTEXT      DEFAULT NULL            COMMENT '设置值',
  `updated_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统设置表';

-- ------------------------------------------------------------
-- 9) 短信验证码表 verification_codes
--    存储注册/登录/绑定手机场景的验证码，5 分钟过期，校验通过后一次性消费（删除）。
--    防刷依赖 created_at（重发间隔 / 单号单 IP 日限额）由 sms_service 计算。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `verification_codes` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `mobile`     VARCHAR(32)     NOT NULL                COMMENT '手机号',
  `code`       VARCHAR(8)      NOT NULL                COMMENT '6位验证码',
  `scene`      VARCHAR(16)     NOT NULL                COMMENT 'register/login/bind',
  `ip`         VARCHAR(64)     DEFAULT NULL            COMMENT '请求IP（防刷）',
  `expire_at`  DATETIME        NOT NULL                COMMENT '过期时间',
  `created_at` DATETIME        NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_mobile_scene` (`mobile`, `scene`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='短信验证码表';

SET FOREIGN_KEY_CHECKS = 1;
-- ------------------------------------------------------------
-- 股票全量代码表（A股 + 港股，已上市）
-- 由后台「股票数据库」同步按钮从 Tushare proxy / AKShare 拉取并 upsert。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `stocks` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `code`        VARCHAR(16)     NOT NULL                COMMENT '交易所原始代码，如 600519 / 00700',
  `ts_code`     VARCHAR(16)     DEFAULT NULL            COMMENT 'Tushare 全代码，如 600519.SH / 00700.HK',
  `name`        VARCHAR(64)     NOT NULL                COMMENT '股票名称',
  `market`      VARCHAR(8)      NOT NULL                COMMENT 'A / HK',
  `exchange`    VARCHAR(12)     DEFAULT NULL            COMMENT 'SH / SZ / HK',
  `list_status` VARCHAR(4)      NOT NULL DEFAULT 'L'    COMMENT 'L=上市 D=退市 P=暂停',
  `updated_at`  DATETIME        NOT NULL                COMMENT '最近同步时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_code_market` (`code`, `market`),
  KEY `idx_name` (`name`),
  KEY `idx_ts_code` (`ts_code`),
  KEY `idx_market_status` (`market`, `list_status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='股票全量代码表（A股+港股）';

-- ------------------------------------------------------------
-- 9) 自选股 / 收藏表 watchlists
--    用户收藏的股票，用于「自选股」列表与快速再分析。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `watchlists` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    BIGINT UNSIGNED NOT NULL                COMMENT '所属用户',
  `ts_code`    VARCHAR(32)     NOT NULL                COMMENT '股票代码(带交易所后缀，如 600519.SH)',
  `stock_name` VARCHAR(64)     NOT NULL                COMMENT '股票名称',
  `note`       VARCHAR(255)    DEFAULT NULL            COMMENT '用户备注',
  `group_name` VARCHAR(32)     NOT NULL DEFAULT ''     COMMENT '分组名(核心仓/观察仓等)',
  `cost`       DECIMAL(12,4)   DEFAULT NULL            COMMENT '持仓成本(元/股)',
  `quantity`   INT UNSIGNED    DEFAULT NULL            COMMENT '持仓数量(股)',
  `created_at` DATETIME        NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_code` (`user_id`, `ts_code`),
  KEY `idx_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='自选股收藏表';


-- 9b) 自选股提醒规则表 watch_alerts
CREATE TABLE IF NOT EXISTS `watch_alerts` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`     BIGINT UNSIGNED NOT NULL                COMMENT '所属用户',
  `ts_code`     VARCHAR(32)     NOT NULL                COMMENT '股票代码',
  `stock_name`  VARCHAR(64)     NOT NULL DEFAULT ''     COMMENT '股票名称',
  `metric`      VARCHAR(16)     NOT NULL DEFAULT 'total_mv' COMMENT '指标: total_mv/price/pct_chg/pe_ttm',
  `operator`    VARCHAR(8)      NOT NULL DEFAULT 'gte'  COMMENT '比较符: gte/lte/between',
  `threshold`   DECIMAL(16,4)   NOT NULL DEFAULT 0      COMMENT '阈值(主)',
  `threshold2`  DECIMAL(16,4)   DEFAULT NULL            COMMENT '区间上界(between 用)',
  `enabled`     TINYINT(1)      NOT NULL DEFAULT 1      COMMENT '是否启用',
  `triggered`   TINYINT(1)      NOT NULL DEFAULT 0      COMMENT '是否已触发(去重)',
  `last_value`  DECIMAL(16,4)   DEFAULT NULL            COMMENT '最近观测值',
  `triggered_at` DATETIME       DEFAULT NULL            COMMENT '最近触发时间',
  `created_at`  DATETIME        NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_user` (`user_id`),
  KEY `idx_enabled` (`enabled`, `triggered`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='自选股提醒规则表';


CREATE TABLE IF NOT EXISTS `news` (
  `gid`              BIGINT UNSIGNED NOT NULL            COMMENT '格隆汇 live id（唯一）',
  `category`         VARCHAR(16)     NOT NULL DEFAULT 'all' COMMENT '拉取渠道: important / all',
  `title`            VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '标题（可能为空）',
  `content`          TEXT                              COMMENT '正文（已去除来源关键词）',
  `create_timestamp` BIGINT          NOT NULL DEFAULT 0  COMMENT '原文发布时间 epoch 秒',
  `news_date`        DATE            DEFAULT NULL,
  `news_time`        TIME            DEFAULT NULL,
  `important`        TINYINT(1)      NOT NULL DEFAULT 0  COMMENT '是否重大',
  `sentiment`        VARCHAR(10)     DEFAULT 'neutral'  COMMENT 'bull/bear/neutral',
  `tags`             VARCHAR(255)    DEFAULT ''         COMMENT '逗号分隔标签',
  `ai_comment`       VARCHAR(512)    DEFAULT ''         COMMENT '本地规则生成的 AI 洞察',
  `likes`            INT UNSIGNED    NOT NULL DEFAULT 0  COMMENT '点赞数（匿名总量）',
  `views`            INT UNSIGNED    NOT NULL DEFAULT 0  COMMENT '浏览量（前台列表曝光计数）',
  `pinned`           TINYINT(1)      NOT NULL DEFAULT 0  COMMENT '是否置顶（后台可管理，置顶排最前）',
  `created_at`       DATETIME        NOT NULL,
  PRIMARY KEY (`gid`),
  KEY `idx_create` (`create_timestamp`),
  KEY `idx_important` (`important`),
  KEY `idx_pinned` (`pinned`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='市场快讯（格隆汇来源，落库每小时更新，展示不写来源）';


-- ------------------------------------------------------------
-- 大盘涨跌投票表 market_votes
--   用户可对每个交易日的大盘方向投票一次（看涨/看跌），可改票。
--   机会页展示真实投票分布，替代原先硬编码的「准确率 85%」假数字。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `market_votes` (
  `id`          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`     INT UNSIGNED NOT NULL                COMMENT '用户 id（未登录时由后端拒绝）',
  `trade_date`  VARCHAR(8)   NOT NULL                COMMENT '投票所属交易日 YYYYMMDD',
  `vote`        TINYINT(1)   NOT NULL                COMMENT '1=看涨 0=看跌',
  `created_at`  DATETIME     NOT NULL,
  `updated_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_date` (`user_id`, `trade_date`),
  KEY `idx_trade_date` (`trade_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='大盘涨跌投票（每用户每交易日一票，可改票）';

-- ------------------------------------------------------------
-- 配额手动调整流水表 bonus_logs
--   管理员在后台手动补/扣用户的一次性赠送分析余量（bonus_normal / bonus_deep），
--   每笔变动写一条流水，形成审计轨迹，避免「偷偷改余额」无法追溯。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `bonus_logs` (
  `id`                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`            BIGINT UNSIGNED NOT NULL          COMMENT '目标用户',
  `admin_id`           BIGINT UNSIGNED DEFAULT NULL      COMMENT '操作管理员 user.id',
  `delta_normal`       INT             NOT NULL DEFAULT 0 COMMENT '普通分析余量变动（正加负减）',
  `delta_deep`         INT             NOT NULL DEFAULT 0 COMMENT '深度分析余量变动（正加负减）',
  `bonus_normal_after` INT             NOT NULL DEFAULT 0 COMMENT '调整后普通余量',
  `bonus_deep_after`   INT             NOT NULL DEFAULT 0 COMMENT '调整后深度余量',
  `reason`             VARCHAR(255)    DEFAULT ''        COMMENT '调整原因',
  `created_at`         DATETIME        NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_user` (`user_id`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='配额手动调整流水（审计轨迹）';
