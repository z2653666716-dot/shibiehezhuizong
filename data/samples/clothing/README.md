# 公开衣物诊断样例

这里是从公开来源下载的参考图片，不是用户摄像头的照片、截图或裁剪。
用途是与已有 `../test.jpg` 一起检查衣物误检和真人漏检，不能据此宣称解决用户现场问题。

- `closet_clothes.jpg`：mycurrency.com（Mycaccount），[原作品](https://commons.wikimedia.org/wiki/File:Clothes_hanged_inside_a_closet.jpg)，[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)。原图未修改，目视确认无真人。
- `window_jacket.jpg`：Demeester，[原作品](https://commons.wikimedia.org/wiki/File:Jacket_hanging_from_window_latch.JPG)，[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/)。使用 Wikimedia 提供的 1280 像素缩略图，本地未再修改；目视确认无真人。
- `gallery_jacket.jpg`：Jocelyn Wu（jocelynwu），[原作品](https://commons.wikimedia.org/wiki/File:Jacket_hanging_in_art_gallery_(Unsplash).jpg)，来源页面记载为 [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)。原图未修改；有两名真人和一件无人穿着的悬挂外套。

图片来源、下载地址、SHA256 校验值、粗略人物框和衣物区域见 `../detection_cases.json`。
坐标按 `[左, 上, 右, 下]` 表示，0～1 是相对于图片宽高的比例。
人物框是目视粗标；运行诊断时应明确标注样本量小、标注粗略，不把结果当成通用准确率或正式 mAP。
复制或分发样例时，请保留本文件与清单中的作者、来源和许可信息。
