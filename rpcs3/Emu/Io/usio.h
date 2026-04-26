#pragma once

#include "Emu/system_utils.hpp"
#include "Emu/Io/usb_device.h"

#include <deque>
#include <initializer_list>
#include <map>
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
	void bngrw_cmd_felica(std::span<const u8> data);
	void bngrw_felica_read(std::span<const u8> data);
	void bngrw_felica_write(std::span<const u8> data);
	std::array<u8, 16>& bngrw_block(u16 block);
	void bngrw_bridge_init();
	void bngrw_bridge_poll();
	void bngrw_bridge_close_client();
	void bngrw_bridge_send_event(std::string_view line);
	void bngrw_bridge_send_state();

private:
	bool is_used = false;
	const std::string usio_backup_path = rpcs3::utils::get_hdd1_dir() + "/caches/usiobackup.bin";
	std::vector<u8> response;
	std::vector<u8> m_bngrw_request;
	std::deque<u8> m_bngrw_response;
	uptr m_bngrw_listen = ~uptr{0};
	uptr m_bngrw_client = ~uptr{0};
	std::string m_bngrw_rx_buffer;

	enum class bngrw_card_type : u8
	{
		none,
		mifare,
		felica
	};

	struct bngrw_card_state
	{
		bngrw_card_type type = bngrw_card_type::none;
		std::array<u8, 4> uid{};
		std::array<u8, 8> idm{};
		std::array<u8, 8> pmm{0x00, 0xf1, 0x00, 0x00, 0x00, 0x01, 0x43, 0x00};
		std::array<u8, 2> system_code{0x88, 0xb4};
		std::map<u16, std::array<u8, 16>> blocks;
	};

	bngrw_card_state m_bngrw_card;
	bngrw_card_state m_bngrw_pending;
	bool m_bngrw_pending_active = false;

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
