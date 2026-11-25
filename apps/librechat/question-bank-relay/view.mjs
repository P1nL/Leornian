export const relayView = `<section id="relay-mesh" lang="zh-CN" aria-labelledby="relay-title">
  <header data-in><h2 id="relay-title">题包协作</h2></header>
  <section class="stage" data-stage aria-label="可拖动的十角色关系网">
    <canvas class="field" data-field role="img" aria-label="十个角色沿不规则多边形排列，亮线表示当前交接。"></canvas>
    <div class="roles" data-roles role="group" aria-label="边缘角色"></div>
  </section>
  <section class="transport" data-in aria-label="消息回放">
    <div class="caption">
      <span class="ordinal" data-count></span><strong data-who></strong><span class="phase" data-phase></span>
    </div>
    <p class="message" data-message aria-live="polite" aria-atomic="true"></p>
    <div class="controls">
      <button class="play" data-play type="button" aria-label="播放消息"><span class="play-symbol" aria-hidden="true"></span></button>
      <div class="timeline">
        <div class="rail" aria-hidden="true"><span class="travel"></span><span class="ticks"></span><span class="thumb"></span></div>
        <input type="range" min="0" step=".01" value="0" data-time aria-label="消息时间轴">
      </div>
      <span class="clock" data-clock aria-hidden="true"></span>
    </div>
  </section>
  <section class="sequence" aria-labelledby="relay-sequence-title">
    <div class="seq-window" data-seq-window>
      <header class="seq-head">
        <h3 id="relay-sequence-title">消息时序</h3>
        <div class="seq-heads" data-seq-heads role="list" aria-label="十个角色"></div>
      </header>
      <div class="seq-sheet">
        <div class="seq-guides" data-seq-guides aria-hidden="true"></div>
        <ol class="seq-list" data-seq-list aria-label="已发消息"></ol>
      </div>
    </div>
  </section>
</section>`;
