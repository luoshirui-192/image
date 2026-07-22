-- One-time: allow storing Bidiso/Neuiso *paths* in T_FEATURE_RECORD.
-- Run on mysql8039 / ara_fp_analyst (fp_user needs ALTER privilege).
--
--   docker exec -i mysql8039 mysql -u fp_user -p ara_fp_analyst < sql/alter_t_feature_record_path_columns.sql

USE `ara_fp_analyst`;

ALTER TABLE `T_FEATURE_RECORD`
  MODIFY COLUMN `feature_ara_data` varchar(500) NULL
    COMMENT 'ara/Bidiso feature storage path (e.g. templates/...)',
  MODIFY COLUMN `feature_neuro_data` varchar(500) NULL
    COMMENT 'NEURO/Neuiso feature storage path (e.g. templates/...)';
