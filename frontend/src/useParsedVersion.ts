import {useCallback, useEffect, useState} from 'react';
import {getParsedVersion} from './api';
import type {ParsedResponse} from './document-types';

export function useParsedVersion(versionId: string | null, revision: number, jobId?:string | null) {
  const key = `${versionId ?? ''}:${jobId ?? ''}`;
  const [value,setValue] = useState<{versionId:string; data:ParsedResponse} | null>(null);
  const [failure,setFailure] = useState<{versionId:string; message:string} | null>(null);
  const [refreshNo,setRefreshNo] = useState(0);
  const refresh = useCallback(() => setRefreshNo(n => n + 1),[]);
  useEffect(() => {
    if (!versionId) return;
    const controller = new AbortController();
    let timer:ReturnType<typeof setTimeout>;
    async function load() {
      let delay = 10000;
      try {
        const data = await getParsedVersion(versionId!,controller.signal,jobId);
        if (controller.signal.aborted) return;
        setValue({versionId:key,data});setFailure(null);
        if (['queued','running'].includes(data.latest_processing?.status ?? '')) delay = 2000;
      } catch (error) {
        if (!controller.signal.aborted) setFailure({versionId:key,message:error instanceof Error ? error.message : '解析结果暂时无法读取'});
      }
      if (!controller.signal.aborted) timer = setTimeout(load,delay);
    }
    void load();
    return () => {controller.abort();clearTimeout(timer);};
  },[versionId,jobId,key,revision,refreshNo]);
  return {data:value?.versionId === key ? value.data : null,
    error:failure?.versionId === key ? failure.message : '',refresh};
}
