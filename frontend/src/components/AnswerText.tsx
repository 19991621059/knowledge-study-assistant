import type {ReactNode} from "react";

// 只处理少量排版语法，所有模型文字都由React转义，不执行HTML或外部链接。
function inline(value: string): ReactNode[] {
  return value.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={index}>{part.slice(2, -2)}</strong> :
      part.startsWith("`") && part.endsWith("`") ? <code key={index}>{part.slice(1, -1)}</code> : part,
  );
}

export function AnswerText({value}: {value: string}) {
  return <div className="answer-text">{value.split(/\n\s*\n/).map((part, index) => {
    const heading = part.match(/^#{1,6}\s+([^\n]+)$/);
    return heading ? <h4 key={index}>{inline(heading[1])}</h4> : <p key={index}>{inline(part)}</p>;
  })}</div>;
}
