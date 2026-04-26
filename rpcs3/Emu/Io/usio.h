#pragma once

#include "Emu/system_utils.hpp"
#include "Emu/Io/usb_device.h"

#include <deque>
#include <initializer_list>
#include <span>

class usb_device_usio : public usb_device_emulated
{
public:
	usb_device_usio(const std::array<u8, 7>& location);
	~usb_device_usio();

	static std::shared_ptr<usb_device> make_instance(u32 controller_index, const std::array<u8, 7>& location);
	static u16 get_num_emu_devices();

	void control_transfer(u8 bmRequestType, u8 bRequest, u16 wValue, u16 wIndex, u16 wLength, u32 buf_size, u8* buf, UsbTransfer* transfer) override;
	void interrupt_transfer(u32 buf_size, u8* buf, u32 endpoint, UsbTransfer* transfer) override;

private:
	void load_backup();
	void save_backup();
	void translate_input_taiko();
	void translate_input_tekken();
	void usio_write(u8 channel, u16 reg, std::vector<u8>& data);
	void usio_read(u8 channel, u16 reg, u16 size);
	void usio_init(u8 channel, u16 reg, u16 size);
	void bngrw_feed_bytes(const u8* data, u32 size);
	void bngrw_handle_frame();
	void bngrw_send_ack();
	void bngrw_send_response(u8 cmd, std::span<const u8> payload = {});
	void bngrw_send_response(u8 cmd, std::initializer_list<u8> payload);
	void bngrw_send_simple_response();
	void bngrw_cmd_gpio(std::span<const u8> data);
	void bngrw_cmd_rf_field(std::span<const u8> data);
	void bngrw_cmd_poll_card();
	void bngrw_cmd_mifare(std::span<const u8> data);
	void bngrw_cmd_commthru();
	void bngrw_cmd_select();
	void bngrw_cmd_deselect();
	void bngrw_cmd_release();
	void bngrw_cmd_felica();

private:
	bool is_used = false;
	const std::string usio_backup_path = rpcs3::utils::get_hdd1_dir() + "/caches/usiobackup.bin";
	std::vector<u8> response;
	std::vector<u8> m_bngrw_request;
	std::deque<u8> m_bngrw_response;

	struct io_status
	{
		bool test_on = false;
		bool test_key_pressed = false;
		bool coin_key_pressed = false;
		le_t<u16> coin_counter = 0;
	};

	std::array<io_status, 2> m_io_status;
};

class usb_device_bngrw : public usb_device_emulated
{
public:
	usb_device_bngrw(const std::array<u8, 7>& location);

	void control_transfer(u8 bmRequestType, u8 bRequest, u16 wValue, u16 wIndex, u16 wLength, u32 buf_size, u8* buf, UsbTransfer* transfer) override;
	void interrupt_transfer(u32 buf_size, u8* buf, u32 endpoint, UsbTransfer* transfer) override;

private:
	void feed_bytes(const u8* data, u32 size);
	void handle_frame();
	void send_ack();
	void send_response(u8 cmd, std::span<const u8> payload = {});
	void send_response(u8 cmd, std::initializer_list<u8> payload);

private:
	std::vector<u8> m_request;
	std::deque<u8> m_response;
};
