import json
import sys
import logging
 
import database
 
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
 
INPUT_FILE = "normalized_listings.jsonl"
 
 
def main():
    skip_review = "--skip-review" in sys.argv
 
    database.init_db()  # đảm bảo bảng/cột đã đầy đủ trước khi insert
 
    added, skipped_dup, skipped_review, failed = 0, 0, 0, 0
 
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(f"Dòng {line_num} lỗi JSON, bỏ qua.")
                failed += 1
                continue
 
            if skip_review and record.get("_can_review"):
                skipped_review += 1
                continue
 
            # Chống trùng: nếu url này đã có trong DB thì bỏ qua
            existing = database.get_room_by_url(record.get("url"))
            if existing:
                skipped_dup += 1
                continue
 
            # Bỏ field nội bộ trước khi insert
            record.pop("_can_review", None)
 
            success = database.add_room(record)
            if success:
                added += 1
            else:
                failed += 1
 
    logger.info("=== KẾT QUẢ IMPORT ===")
    logger.info(f"Đã thêm mới: {added}")
    logger.info(f"Bỏ qua vì trùng url đã có: {skipped_dup}")
    if skip_review:
        logger.info(f"Bỏ qua vì cần review thủ công: {skipped_review}")
    logger.info(f"Lỗi khi insert: {failed}")
 
 
if __name__ == "__main__":
    main()