/*
  Warnings:

  - You are about to drop the column `rating` on the `reviews` table. All the data in the column will be lost.
  - You are about to drop the `seasonal_multipliers` table. If the table is not empty, all the data it contains will be lost.

*/
-- DropForeignKey
ALTER TABLE "seasonal_multipliers" DROP CONSTRAINT "seasonal_multipliers_created_by_fkey";

-- DropForeignKey
ALTER TABLE "seasonal_multipliers" DROP CONSTRAINT "seasonal_multipliers_updated_by_fkey";

-- DropIndex
DROP INDEX "reviews_rating_idx";

-- AlterTable
ALTER TABLE "reviews" DROP COLUMN "rating";

-- DropTable
DROP TABLE "seasonal_multipliers";
