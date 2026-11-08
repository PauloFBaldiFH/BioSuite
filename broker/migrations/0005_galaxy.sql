-- BioSuite stores the local origin per installation, not an arbitrary URL.
ALTER TABLE enrollments ADD COLUMN origin_port INTEGER NOT NULL DEFAULT 8080 CHECK(origin_port BETWEEN 1024 AND 65535);
ALTER TABLE libraries ADD COLUMN origin_port INTEGER NOT NULL DEFAULT 8080 CHECK(origin_port BETWEEN 1024 AND 65535);
