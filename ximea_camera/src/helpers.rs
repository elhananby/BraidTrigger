use super::structs::Args;
use ctrlc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use xiapi;

pub fn time() -> f64 {
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(duration) => {
            let seconds = duration.as_secs() as f64; // Convert seconds to f64
            let nanos = duration.subsec_nanos() as f64; // Convert nanoseconds to f64
            seconds + nanos / 1_000_000_000.0 // Combine both into a single f64 value
        }
        Err(_) => panic!("SystemTime before UNIX EPOCH!"),
    }
}

fn get_offset_for_resolution(
    max_resolution: (u32, u32),
    width: u32,
    height: u32,
) -> Result<(u32, u32), i32> {
    let mut offset_x = (max_resolution.0 - width) / 2;
    let mut offset_y = (max_resolution.1 - height) / 2;

    offset_x = ((offset_x as f32 / 32.0).ceil() * 32 as f32) as u32;
    offset_y = ((offset_y as f32 / 32.0).ceil() * 32 as f32) as u32;
    log::debug!("Offset x = {}, Offset y = {}", offset_x, offset_y);
    Ok((offset_x, offset_y))
}

pub fn set_camera_parameters(cam: &mut xiapi::Camera, args: &Args) -> Result<(), i32> {
    cam.set_exposure(args.exposure)?;
    cam.set_image_data_format(xiapi::XI_IMG_FORMAT::XI_MONO8)?;
    cam.set_acq_timing_mode(xiapi::XI_ACQ_TIMING_MODE::XI_ACQ_TIMING_MODE_FRAME_RATE_LIMIT)?;
    cam.set_framerate(args.fps)?;
    cam.set_limit_bandwidth(cam.limit_bandwidth_maximum()?)?;
    let buffer_size = cam.acq_buffer_size()?;
    cam.set_acq_buffer_size(buffer_size * 4)?;
    cam.set_buffers_queue_size(cam.buffers_queue_size_maximum()?)?;

    cam.recent_frame()?;

    let max_resolution = cam.roi().unwrap();
    let (offset_x, offset_y) = get_offset_for_resolution(
        (max_resolution.width, max_resolution.height),
        args.width,
        args.height,
    )?;

    let roi = xiapi::Roi {
        offset_x,
        offset_y,
        width: args.width,
        height: args.height,
    };
    let actual_roi = cam.set_roi(&roi);

    log::debug!(
        "Current resolution = {:?}x{:?}",
        actual_roi.as_ref().unwrap().width,
        actual_roi.as_ref().unwrap().height
    );
    Ok(())
}

pub fn connect_to_zmq(addr: &str) -> Result<zmq::Socket, zmq::Error> {
    let context = zmq::Context::new();
    let socket = context.socket(zmq::SUB)?;
    socket.connect(format!("tcp://{}", addr).as_str())?;
    socket.set_subscribe(b"").unwrap();
    Ok(socket)
}

pub fn setup_ctrlc_handler(running: Arc<AtomicBool>) {
    ctrlc::set_handler(move || {
        running.store(false, Ordering::SeqCst);
    })
    .expect("Error setting Ctrl-C handler");
}