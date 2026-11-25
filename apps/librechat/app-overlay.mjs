export function removeSilentAudio(source) {
  const frame = /\n[ \t]*<iframe\s+src="assets\/silence\.mp3"[^>]*\/>/g;
  if ([...source.matchAll(frame)].length !== 1) {
    throw new Error('Pinned LibreChat silent audio iframe changed.');
  }
  return source.replace(frame, '');
}
