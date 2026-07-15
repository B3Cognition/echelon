declare module 'picomatch' {
  type Matcher = (input: string) => boolean;

  function picomatch(pattern: string | string[], options?: Record<string, unknown>): Matcher;

  export = picomatch;
}
