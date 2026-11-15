import {useEffect, useState} from 'react';

export default function TextOriginal({url}: {url: string}) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setText(null); setError('');
    fetch(url,{signal:controller.signal}).then(response => {
      if (!response.ok) throw new Error('原件暂时无法读取，请使用新窗口打开。');
      return response.text();
    }).then(value => { if (!controller.signal.aborted) setText(value); })
      .catch(() => { if (!controller.signal.aborted) setError('原件暂时无法读取，请使用新窗口打开。'); });
    return () => controller.abort();
  },[url]);
  return error ? <p role="alert" className="form-error">{error}</p> : text === null
    ? <p role="status" className="empty-note">正在读取原件…</p> : <pre className="original-markdown">{text}</pre>;
}
