-- Minimal Prisma-owned schema for CI Postgres integration tests.
-- In production these are created by the Next.js repo's Prisma migrations;
-- CI has no Prisma, so we recreate just the enums + tables the Django
-- integration tests touch. Column shapes mirror the Prisma init migration.

CREATE TYPE "WorkoutSplit" AS ENUM
  ('PPL', 'UPPER_LOWER', 'BRO', 'FULL_BODY', 'CUSTOM');
CREATE TYPE "FoodSource" AS ENUM ('INDB', 'IFCT', 'USDA', 'MANUAL');

CREATE TABLE users (
    id         TEXT PRIMARY KEY,
    email      TEXT NOT NULL,
    name       TEXT,
    avatar_url TEXT,
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP(3) NOT NULL
);

CREATE TABLE workout_templates (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    split_type "WorkoutSplit",
    exercises  JSONB NOT NULL,
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP(3) NOT NULL
);

CREATE TABLE foods (
    id                    TEXT PRIMARY KEY,
    name                  TEXT NOT NULL,
    name_hindi            TEXT,
    source                "FoodSource" NOT NULL,
    category              TEXT,
    calories_per_100g     DOUBLE PRECISION NOT NULL,
    protein_per_100g      DOUBLE PRECISION NOT NULL,
    carbs_per_100g        DOUBLE PRECISION NOT NULL,
    fat_per_100g          DOUBLE PRECISION NOT NULL,
    fiber_per_100g        DOUBLE PRECISION,
    default_unit          TEXT NOT NULL DEFAULT 'g',
    default_quantity      DOUBLE PRECISION NOT NULL DEFAULT 100,
    default_grams         DOUBLE PRECISION NOT NULL DEFAULT 100,
    restaurant_multiplier DOUBLE PRECISION NOT NULL DEFAULT 1.5,
    is_verified           BOOLEAN NOT NULL DEFAULT false,
    created_at            TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP
);
