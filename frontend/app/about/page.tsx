// 소개 페이지. 서비스 화면과 따로 둔다.
// 처음 온 사람이 "이게 뭘 해주는 도구인가"를 30초 안에 알고 돌아가게 하는 것이 목적이라,
// 기능 목록 대신 어떤 답을 내놓는지 예시 하나를 먼저 보여준다.

import Link from "next/link";

export const metadata = {
  title: "Converge 소개",
  description: "어디서 몇 시에 만날까를 문장 하나로 끝내는 약속 에이전트",
};

const STEPS = [
  ["문장을 넣는다", "카톡에 쓰듯 그대로 쓴다. 참석자·출발지·이동수단을 알아서 뽑는다"],
  ["출발지를 확인한다", "지도에 핀이 먼저 뜬다. 틀리면 끌어다 놓거나 검색해서 고친다"],
  ["집결지를 받는다", "왜 그곳인지, 왜 다른 곳이 아닌지를 같이 말한다"],
  ["각자 출발 시각을 받는다", "도착 기한에서 절차 소요·이동·여유를 거꾸로 뺀 값이다"],
  ["링크를 공유한다", "참석자가 들어와 자기 출발지를 직접 고칠 수 있다"],
];

const DIFFERENT = [
  ["출발 시각을 역산한다", "지도 앱은 여기서 저기까지 몇 분인지까지만 말한다. 정작 필요한 답은 내가 몇 시에 나가야 하는가다"],
  ["안 고른 자리도 말한다", "후보를 하나만 던지지 않는다. 다른 자리가 왜 아닌지를 같이 보여줘야 이야기가 끝난다"],
  ["준비물을 나눈다", "미리 신청해야 하는 것과 당일 챙기는 것은 다르다. 늦으면 되돌릴 수 없는 쪽을 앞에 둔다"],
  ["모르면 되묻는다", "빈칸을 채워 넣지 않는다. 출입 절차가 있는지, 몇 시인지 모르면 묻는다"],
];

export default function AboutPage() {
  return (
    <main className="landing-body">
      <section className="intro">
        <h1>어디서 몇 시에 만날까</h1>
        <p>
          여럿이 만날 때 사람이 머리로 하던 계산을 대신합니다. 각자 어디서 출발하는지, 무엇을 타는지,
          도착해서 무슨 절차를 거쳐야 하는지를 넣으면 집결 장소와 시각, 각자 나서야 하는 시각을
          지도 위에 내놓습니다.
        </p>
      </section>

      <section className="about-block">
        <h2>이런 답을 받습니다</h2>
        <pre className="summary">{`저녁 8시 강남 사무실에서 회의. 나는 송파구, 김대리는 강서구, 둘 다 지하철.
1층에서 출입증 받고 올라가야 함.

  집결: 사무실 1층 19:50
  김대리  19:05 출발 · 지하철 45분
  나      19:15 출발 · 지하철 35분
  20:00 시작, 출입 절차 10분 전 도착 기준
  미리 해둘 것: [미완료] 방문자 등록
  당일 챙길 것: 신분증, 출입증 수령`}</pre>
        <p className="muted">
          합류 지점이 강남역이 아니라 1층인 이유는 출입 절차가 거기서 시작되기 때문입니다.
          역에서 만나 같이 가도 절차는 어차피 1층에서 시작됩니다.
        </p>
      </section>

      <section className="about-block">
        <h2>쓰는 순서</h2>
        <ol className="how">
          {STEPS.map(([title, detail]) => (
            <li key={title}>
              <strong>{title}</strong> {detail}
            </li>
          ))}
        </ol>
      </section>

      <section className="about-block">
        <h2>다른 점</h2>
        <ul className="how">
          {DIFFERENT.map(([title, detail]) => (
            <li key={title}>
              <strong>{title}</strong> {detail}
            </li>
          ))}
        </ul>
      </section>

      <section className="about-block">
        <h2>하지 않는 것</h2>
        <ul className="how">
          <li>출발 후 실시간 길안내와 재탐색. 그건 내비의 영역입니다</li>
          <li>식당 예약, 영업시간 확인</li>
          <li>참석자 정보를 따로 모아 두는 일. 출발지·좌표·경로는 암호화해 보관하고 약속이 지나면 지웁니다</li>
        </ul>
      </section>

      <p>
        <Link href="/">약속 잡으러 가기</Link>
      </p>
    </main>
  );
}
