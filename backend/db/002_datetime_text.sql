-- 002: sessions.datetime_text (09-27)
-- 날짜 없이 시각만 말한 약속("저녁 7시")은 meet_at 이 없어 재질문 때마다 시각을 다시 물었다.
-- 사람이 말한 원문을 남겨 되살린다. 개인정보가 아니라 평문으로 둔다 (테이블정의서 1절).
-- 001 로 이미 만든 DB(Supabase)에만 필요하다. 새로 만드는 DB 는 001 에 이미 들어 있어 그냥 지나간다.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS datetime_text text;
