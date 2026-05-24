from comicfeed.downloader import download_gallery


async def test_download_gallery_to_cbz(tmp_path, nhentai_credentials):
    """下载完整画廊并打包为 CBZ 文件。"""
    from comicfeed.sources.nhentai import NhentaiSource

    source = NhentaiSource(credentials=nhentai_credentials)
    # 小画廊 103110: 35 pages, split into 2 volumes
    result = await download_gallery(
        source=source,
        gallery_id="103110",
        output_dir=str(tmp_path),
        cbz_max_pages=30,
    )
    assert len(result.files) == 2  # 35 pages / 30 = 2 volumes
    assert result.files[0].endswith("(0001-0030).cbz")
    assert result.files[1].endswith("(0031-0035).cbz")
