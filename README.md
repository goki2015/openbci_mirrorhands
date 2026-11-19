# openbci_mirrorhands
This repository is sample code of driving mirrorhands with openbci.<br>
I made openbci programs with Rust at first and remake this by using Python.<br>
My PC is low performance, so I need to use RUST for online process.but if I can use lab's PC..<br>.

temporary memo
# キャリブレーション
フィルター処理されたデータ(RMS)はAdaptiveThreshold._compute()に送られ
rest,girpそれぞれの窓のうち、全体ソートの50%付近の値を取得される
それを幾何平均してanchorを出す。
rest_ubとgirp_lbをそれぞれ、全体ソートの90%,10%付近の値に設定して
これらの間をgap_dbとしてデシベル表記にする。
ここで、前回までは窓全体のRMSに対して、意図的に差が小さくなるような値を撮っている。

そして、きちんと離れていることが確認されたら、
現在のanchorを利用して（それかrestの1．5倍より下回ったらそっち）、girpを設定これを基準にthを設定
それぞれの比率からrestとnoiseのしきい値を設定して終わり。

---
#フィルタ
フィルタ自体の式は既存のものを用いて、その係数はscipyがf0,qその他パラメータの値から設定する。
frのノッチ周波数がリストで与えられて、その部分のフィルタが与えられる。
なるほど、secsはフィルタの係数リストのようなものか？
sosはbutterwirthの係数
sosのループ処理もまた、係数をsecsに入れる。ここを見ればsosででどんな値が返ってきたのかわかりやすい
係数が出揃ったら、secのうちノッチフィルタの係数セットがどこまでかを見る。
双一次変換でデジタルのカットオフ周波数をアナログのカットオフ周波数へ、詳しくは26/11/16の研究ノート
周波数fcも同様に求める、虚軸のΩ=0の部分に。
gは…何？あとでbにかけていることを見るとゲインの調整？なぜこの式？

StreamingFilterは純py側の実装のクラスをそのまま継承。
メインのBiquadオブジェクトを作成する。

## 純py側の処理
biquadお決まりの形の伝達関数を作っておく。
        b0 + b1·z⁻¹ + b2·z⁻²
H(z) = ───────────────────────
        1  + a1·z⁻¹ + a2·z⁻²
これを差分方程式として置き換えたものが
Biquadの式で
b0,b1,b2,a1,a2をb=[g,-c,g],a=[1,-c,2g-1]としたらノッチフィルタ
b=[1,0,-1],a=極のペア
各区係数はscipy側が出すので_notch,_bandpass,_biquadは割愛
_validate関数で与えられた数値が、基準（例えばfs>0,orderは1~12までとか）を満たすか確認
_Cleanerは異常なサンプルを補正するために使用する。
push()が本体で、無限大や、小さすぎる値、０等に該当しないなら値を更新
該当するななら、直線で予測してself.max_exを超えたらそれ以降は直前の値保持。
_Medianはbufから到着順に値を調査、sortされた内容から二分探索で古いものを削除を繰り返して窓を更新して、中央値を取る
_RMSはシンプルに式通り

process_oneはこれらの関数を順次実行
x → [ノッチ50] → [ノッチ100] → [BP1] → [BP2] → [BP3] → [BP4] → y
         同じ _Biquad クラスのインスタンスで、係数だけが違う
