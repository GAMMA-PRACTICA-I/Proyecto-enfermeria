from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_rename_studentacademicos_studentacademic_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=r"""
            CREATE TABLE IF NOT EXISTS `student_field_review` (
              `id` bigint NOT NULL AUTO_INCREMENT,
              `section` varchar(80) NOT NULL,
              `field_key` varchar(120) NOT NULL,
              `status` varchar(20) NOT NULL,
              `notes` longtext NULL,
              `reviewed_at` datetime(6) NOT NULL,
              `ficha_id` bigint NOT NULL,
              `reviewed_by_id` bigint DEFAULT NULL,
              PRIMARY KEY (`id`),
              UNIQUE KEY `uniq_ficha_field_key` (`ficha_id`,`field_key`),
              KEY `idx_field_ficha_key` (`ficha_id`,`field_key`),
              KEY `idx_field_ficha_status` (`ficha_id`,`status`),
              CONSTRAINT `student_field_review_ficha_fk`
                FOREIGN KEY (`ficha_id`) REFERENCES `student_ficha` (`id`)
                ON DELETE CASCADE,
              CONSTRAINT `student_field_review_reviewer_fk`
                FOREIGN KEY (`reviewed_by_id`) REFERENCES `accounts_user` (`id`)
                ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """,
            reverse_sql="DROP TABLE IF EXISTS `student_field_review`;",
        ),
    ]
