-- 003: results.rendezvous_legs_enc (09-27)
-- 두 단계 집결에서 무리가 집결지 → 후보로 함께 가는 경로선. 지도에 그리고 공유 링크로 다시 열 때도 보인다.
-- 경로선은 위치정보라 다른 경로처럼 암호화한다 (테이블정의서 7절).
-- 001 로 이미 만든 DB 에만 필요하다. 새 DB 는 001 에 이미 들어 있어 그냥 지나간다.
ALTER TABLE results ADD COLUMN IF NOT EXISTS rendezvous_legs_enc bytea;
